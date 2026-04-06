from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
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


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_tick_executes_pending_queue_tasks(monkeypatch):
    scheduler = TaskScheduler()
    task = _make_task()
    queue_entry = SimpleNamespace(id=uuid4(), task_id=task.id, status=TaskStatus.pending)

    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.get_due_schedules", AsyncMock(return_value=[]))
    get_all = AsyncMock(return_value=[queue_entry])
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.get_all", get_all)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskExecutor.execute_task", AsyncMock(return_value={"success": True}))
    update_task = AsyncMock()
    update_queue = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)

    await scheduler.tick()
    await asyncio.gather(*scheduler.active_tasks)

    assert get_all.await_args.kwargs["available_at"] is not None
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


@pytest.mark.asyncio
async def test_execute_schedule_uses_payload_agent_instance_id_when_template_agent_missing(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    agent_instance_id = uuid4()
    template_task = Task(
        id=uuid4(),
        user_id=uuid4(),
        agent_id=None,
        parent_task_id=None,
        task_type="scheduled_method",
        status=TaskStatus.pending,
        priority=Priority.normal,
        payload={
            "task_execution_type": "method",
            "method_path": "agent.bulter@Bulter.review_msg",
            "agent_instance_id": str(agent_instance_id),
        },
        result=None,
        error_message=None,
        retry_count=0,
        max_retries=3,
        session_id=None,
    )
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
    create_task = AsyncMock(return_value=execution_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", create_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.create", AsyncMock(return_value=queue_entry))
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(return_value={"success": True}),
    )
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", AsyncMock())
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", AsyncMock())
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.update", AsyncMock())
    monkeypatch.setattr(
        "scheduler.task_scheduler.calculate_next_run",
        lambda *_args, **_kwargs: current_time + timedelta(days=1),
    )

    await scheduler._execute_schedule(schedule, current_time)

    created_dto = create_task.await_args.args[0]
    assert created_dto.agent_id == agent_instance_id


@pytest.mark.asyncio
async def test_execute_schedule_missing_agent_reference_deactivates_schedule_without_creating_task(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    template_task = Task(
        id=uuid4(),
        user_id=uuid4(),
        agent_id=None,
        parent_task_id=None,
        task_type="scheduled_method",
        status=TaskStatus.pending,
        priority=Priority.normal,
        payload={
            "task_execution_type": "method",
            "method_path": "agent.bulter@Bulter.review_msg",
        },
        result=None,
        error_message=None,
        retry_count=0,
        max_retries=3,
        session_id=None,
    )
    schedule = SimpleNamespace(
        id=uuid4(),
        task_template_id=template_task.id,
        next_run_at=current_time,
        schedule_expression="0 17 * * *",
        schedule_type=ScheduleType.cron,
        retry_count=0,
    )

    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=template_task))
    create_task = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", create_task)
    execute_task = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskExecutor.execute_task", execute_task)
    update_schedule = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.update", update_schedule)

    await scheduler._execute_schedule(schedule, current_time)

    create_task.assert_not_awaited()
    execute_task.assert_not_awaited()
    update_dto = update_schedule.await_args.args[0]
    assert update_dto.id == schedule.id
    assert update_dto.is_active is False
    assert update_dto.last_run_at == current_time
    assert update_dto.retry_count is None
    assert update_dto.next_run_at is None


@pytest.mark.asyncio
async def test_tick_skips_pending_queue_entries_scheduled_in_future(monkeypatch):
    scheduler = TaskScheduler()
    task = _make_task()
    queue_entry = SimpleNamespace(
        id=uuid4(),
        task_id=task.id,
        status=TaskStatus.pending,
        scheduled_at=datetime(2026, 4, 4, 6, 1, 0, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        "scheduler.task_scheduler.now_utc",
        lambda: datetime(2026, 4, 4, 6, 0, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.get_due_schedules", AsyncMock(return_value=[]))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.get_all", AsyncMock(return_value=[queue_entry]))
    get_task = AsyncMock(return_value=task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", get_task)

    await scheduler.tick()

    get_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_schedule_failure_uses_backoff_retry(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    template_task = _make_task()
    execution_task = _make_task()
    schedule = SimpleNamespace(
        id=uuid4(),
        task_template_id=template_task.id,
        next_run_at=current_time,
        schedule_expression="0 17 * * *",
        schedule_type=ScheduleType.cron,
        retry_count=0,
    )
    queue_entry = SimpleNamespace(id=uuid4())

    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=template_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", AsyncMock(return_value=execution_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.create", AsyncMock(return_value=queue_entry))
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    update_task = AsyncMock()
    update_queue = AsyncMock()
    update_schedule = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.update", update_schedule)

    await scheduler._execute_schedule(schedule, current_time)

    update_dto = update_schedule.await_args.args[0]
    assert update_dto.id == schedule.id
    assert update_dto.retry_count == 1
    assert update_dto.next_run_at == current_time + timedelta(seconds=30)
    assert update_dto.last_run_at is None


@pytest.mark.asyncio
async def test_execute_schedule_success_resets_retry_count(monkeypatch):
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
        retry_count=4,
    )
    queue_entry = SimpleNamespace(id=uuid4())

    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=template_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", AsyncMock(return_value=execution_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.create", AsyncMock(return_value=queue_entry))
    monkeypatch.setattr("scheduler.task_scheduler.TaskExecutor.execute_task", AsyncMock(return_value={"success": True}))
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

    update_dto = update_schedule.await_args.args[0]
    assert update_dto.retry_count == 0
    assert update_dto.next_run_at == expected_next_run


@pytest.mark.asyncio
async def test_execute_schedule_reuses_one_session_for_scheduler_dao_calls(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    expected_next_run = datetime(2026, 4, 4, 17, 0, 0, tzinfo=timezone.utc)
    template_task = _make_task()
    execution_task = _make_task()
    queue_entry = SimpleNamespace(id=uuid4())
    schedule = SimpleNamespace(
        id=uuid4(),
        task_template_id=template_task.id,
        next_run_at=current_time,
        schedule_expression="0 17 * * *",
        schedule_type=ScheduleType.cron,
        retry_count=0,
    )
    fake_session = object()
    fake_engine = AsyncMock()

    monkeypatch.setattr("scheduler.task_scheduler.create_engine", lambda: fake_engine, raising=False)
    monkeypatch.setattr(
        "scheduler.task_scheduler.async_sessionmaker",
        lambda *_args, **_kwargs: (lambda: _FakeSessionContext(fake_session)),
        raising=False,
    )

    get_by_id = AsyncMock(return_value=template_task)
    create_task = AsyncMock(return_value=execution_task)
    dependencies_met = AsyncMock(return_value=True)
    create_queue = AsyncMock(return_value=queue_entry)
    update_task = AsyncMock()
    update_queue = AsyncMock()
    update_schedule = AsyncMock()

    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", get_by_id)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", create_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", dependencies_met)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.create", create_queue)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.update", update_schedule)
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(return_value={"success": True}),
    )
    monkeypatch.setattr(
        "scheduler.task_scheduler.calculate_next_run",
        lambda *_args, **_kwargs: expected_next_run,
    )

    await scheduler._execute_schedule(schedule, current_time)

    assert get_by_id.await_args.kwargs["session"] is fake_session
    assert create_task.await_args.kwargs["session"] is fake_session
    assert dependencies_met.await_args.kwargs["session"] is fake_session
    assert create_queue.await_args.kwargs["session"] is fake_session
    assert update_task.await_args_list[0].kwargs["session"] is fake_session
    assert update_queue.await_args_list[0].kwargs["session"] is fake_session
    assert update_schedule.await_args.kwargs["session"] is fake_session
    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_schedule_failure_after_five_attempts_uses_one_hour_backoff(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    template_task = _make_task()
    execution_task = _make_task()
    schedule = SimpleNamespace(
        id=uuid4(),
        task_template_id=template_task.id,
        next_run_at=current_time,
        schedule_expression="0 17 * * *",
        schedule_type=ScheduleType.cron,
        retry_count=4,
    )
    queue_entry = SimpleNamespace(id=uuid4())

    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.get_by_id", AsyncMock(return_value=template_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.create", AsyncMock(return_value=execution_task))
    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.create", AsyncMock(return_value=queue_entry))
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    update_task = AsyncMock()
    update_queue = AsyncMock()
    update_schedule = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)
    monkeypatch.setattr("scheduler.task_scheduler.TaskScheduleDAO.update", update_schedule)

    await scheduler._execute_schedule(schedule, current_time)

    update_dto = update_schedule.await_args.args[0]
    assert update_dto.retry_count == 5
    assert update_dto.next_run_at == current_time + timedelta(minutes=60)


@pytest.mark.asyncio
async def test_execute_agent_to_agent_queue_failure_requeues_with_backoff(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    task = _make_task()
    task = task.model_copy(update={"retry_count": 0, "max_retries": 0})
    queue_entry = SimpleNamespace(
        id=uuid4(),
        task_id=task.id,
        status=TaskStatus.pending,
        retry_count=0,
        max_retries=0,
        scheduled_at=None,
    )

    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(side_effect=RuntimeError("delegate failed")),
    )

    update_task = AsyncMock()
    update_queue = AsyncMock()
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)

    await scheduler._execute_queue_entry(queue_entry, task, current_time)

    task_retry_update = update_task.await_args_list[-1].args[0]
    queue_retry_update = update_queue.await_args_list[-1].args[0]
    assert task_retry_update.status == TaskStatus.pending
    assert task_retry_update.retry_count == 1
    assert task_retry_update.scheduled_at == current_time + timedelta(seconds=30)
    assert queue_retry_update.status == TaskStatus.pending
    assert queue_retry_update.retry_count == 1
    assert queue_retry_update.scheduled_at == current_time + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_execute_queue_entry_reuses_one_session_for_scheduler_dao_calls(monkeypatch):
    scheduler = TaskScheduler()
    current_time = datetime(2026, 4, 4, 4, 9, 20, tzinfo=timezone.utc)
    task = _make_task()
    queue_entry = SimpleNamespace(id=uuid4(), task_id=task.id, status=TaskStatus.pending)
    fake_session = object()
    fake_engine = AsyncMock()

    monkeypatch.setattr("scheduler.task_scheduler.create_engine", lambda: fake_engine, raising=False)
    monkeypatch.setattr(
        "scheduler.task_scheduler.async_sessionmaker",
        lambda *_args, **_kwargs: (lambda: _FakeSessionContext(fake_session)),
        raising=False,
    )

    dependencies_met = AsyncMock(return_value=True)
    update_task = AsyncMock()
    update_queue = AsyncMock()

    monkeypatch.setattr("scheduler.task_scheduler.TaskDependencyDAO.are_dependencies_met", dependencies_met)
    monkeypatch.setattr("scheduler.task_scheduler.TaskDAO.update", update_task)
    monkeypatch.setattr("scheduler.task_scheduler.TaskQueueDAO.update", update_queue)
    monkeypatch.setattr(
        "scheduler.task_scheduler.TaskExecutor.execute_task",
        AsyncMock(return_value={"success": True}),
    )

    await scheduler._execute_queue_entry(queue_entry, task, current_time)

    assert dependencies_met.await_args.kwargs["session"] is fake_session
    assert update_task.await_args_list[0].kwargs["session"] is fake_session
    assert update_queue.await_args_list[0].kwargs["session"] is fake_session
    fake_engine.dispose.assert_awaited_once()


def test_seconds_until_next_minute_boundary_aligns_to_second_zero():
    current_time = datetime(2026, 4, 4, 6, 47, 50, 864884, tzinfo=timezone.utc)

    delay = seconds_until_next_minute_boundary(current_time)

    assert delay == pytest.approx(9.135116)
