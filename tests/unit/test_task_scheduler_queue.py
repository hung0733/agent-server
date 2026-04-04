from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

sys.modules.setdefault("isodate", types.SimpleNamespace(parse_duration=lambda *_a, **_k: None))

from db.dto.task_dto import Task
from db.types import Priority, ScheduleType, TaskStatus
from scheduler.task_scheduler import TaskScheduler, seconds_until_next_minute_boundary


def _make_task() -> Task:
    return Task(
        id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        parent_task_id=None,
        task_type="agent_to_agent",
        status=TaskStatus.pending,
        priority=Priority.normal,
        payload={"task_execution_type": "agent_to_agent", "requester_agent_id": str(uuid4())},
        result=None,
        error_message=None,
        retry_count=0,
        max_retries=3,
        session_id=None,
    )


@pytest.mark.asyncio
async def test_tick_executes_pending_queue_tasks(monkeypatch):
    scheduler = TaskScheduler()
    task = _make_task()
    queue_entry = SimpleNamespace(id=uuid4(), task_id=task.id, status=TaskStatus.pending)

    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.get_due_schedules", AsyncMock(return_value=[]))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.get_all", AsyncMock(return_value=[queue_entry]))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskExecutor.execute_task", AsyncMock(return_value={"success": True}))
    update_task = AsyncMock()
    update_queue = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)

    await scheduler.tick()
    await asyncio.gather(*scheduler.active_tasks)

    assert update_task.await_count >= 2
    assert update_queue.await_count >= 2


@pytest.mark.asyncio
async def test_execute_schedule_busy_agent_keeps_schedule_cadence(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    expected_next_run = datetime(2026, 4, 4, 17, 0, 0, tzinfo=timezone.utc)
    template_task = _make_task()
    execution_task = _make_task()
    schedule = SimpleNamespace(
        id=uuid4(),
        task_template_id=template_task.id,
        next_run_at=current_time,
        schedule_expression="0 17 * * *",
        schedule_type=ScheduleType.cron,
    )
    queue_entry = SimpleNamespace(id=uuid4())

    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=template_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", AsyncMock(return_value=execution_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.create", AsyncMock(return_value=queue_entry))
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(side_effect=ValueError("Agent 不是 idle 狀態，無法執行任務")),
    )
    monkeypatch.setattr(
        "scheduler.task_scheduler.calculate_next_run",
        lambda *_args, **_kwargs: expected_next_run,
    )

    update_task = AsyncMock()
    update_queue = AsyncMock()
    update_schedule = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.update", update_schedule)

    await scheduler._execute_schedule(schedule, current_time)

    update_schedule.assert_awaited_once()
    update_dto = update_schedule.await_args.args[0]
    assert update_dto.id == schedule.id
    assert update_dto.next_run_at == expected_next_run
    assert update_dto.next_run_at != current_time


def test_seconds_until_next_minute_boundary_aligns_to_second_zero():
    current_time = datetime(2026, 4, 4, 6, 47, 50, 864884, tzinfo=timezone.utc)

    delay = seconds_until_next_minute_boundary(current_time)

    assert delay == pytest.approx(9.135116)
