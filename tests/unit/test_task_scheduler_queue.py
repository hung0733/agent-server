from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

sys.modules.setdefault("isodate", types.SimpleNamespace(parse_duration=lambda *_a, **_k: None))

from db.dto.task_dto import Task
from db.types import Priority, TaskStatus
from scheduler.task_scheduler import TaskScheduler


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
