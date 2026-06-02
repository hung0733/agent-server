from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.queues.task_queue import (
    TaskQueue,
    TaskQueueHandlerResult,
    TaskQueueStep,
    _retry_delay,
)


class FakeSession:
    commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        type(self).commits += 1


class FakeAssignedTaskDAO:
    rows = []
    marked = []
    logs = []
    cleared = []
    failed_count = 0
    process_count = 0

    def __init__(self, session):
        self.session = session

    async def list_due_pending_steps(self, *, now, limit, excluded_responsible_agent_ids):
        return [
            row
            for row in type(self).rows
            if row[1] not in excluded_responsible_agent_ids
        ][:limit]

    async def mark_step_processing(self, *, step_db_id, now):
        type(self).marked.append((step_db_id, now))
        return True

    async def count_process_logs(self, *, step_db_id):
        return type(self).process_count

    async def count_failed_process_logs(self, *, step_db_id):
        return type(self).failed_count

    async def create_process_log(self, **kwargs):
        type(self).logs.append(kwargs)

    async def clear_step_processing(self, **kwargs):
        type(self).cleared.append(kwargs)


def _session_factory():
    return FakeSession()


def _step(step_db_id: int, task_db_id: int = 10):
    return SimpleNamespace(
        id=step_db_id,
        step_id=f"step-{step_db_id}",
        task_id=task_db_id,
        task=SimpleNamespace(task_id=f"task-{task_db_id}"),
        agent_type="brainstormer",
        title="Brainstorm",
        goal="Collect requirements",
        seq_no=1,
    )


def _reset_fakes():
    FakeSession.commits = 0
    FakeAssignedTaskDAO.rows = []
    FakeAssignedTaskDAO.marked = []
    FakeAssignedTaskDAO.logs = []
    FakeAssignedTaskDAO.cleared = []
    FakeAssignedTaskDAO.failed_count = 0
    FakeAssignedTaskDAO.process_count = 0


@pytest.mark.asyncio
async def test_task_queue_enqueues_due_pending_step(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123)]

    async def handler(task):
        return TaskQueueHandlerResult(success=True)

    queue = TaskQueue(handler, session_factory=_session_factory)
    await queue._enqueue_due_steps()

    queued = await queue._queue.get()
    assert queued.step_db_id == 1
    assert queued.responsible_agent_id == 123
    assert FakeAssignedTaskDAO.marked[0][0] == 1
    assert 123 in queue._active_responsible_agent_ids


@pytest.mark.asyncio
async def test_task_queue_serializes_same_responsible_agent(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123), (_step(2), 123)]

    async def handler(task):
        return TaskQueueHandlerResult(success=True)

    queue = TaskQueue(handler, max_concurrency=4, session_factory=_session_factory)
    await queue._enqueue_due_steps()

    assert queue._queue.qsize() == 1
    assert FakeAssignedTaskDAO.marked == [(1, FakeAssignedTaskDAO.marked[0][1])]


@pytest.mark.asyncio
async def test_task_queue_records_success_log(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.process_count = 2
    started_at = datetime.now(timezone.utc)
    task = TaskQueueStep(1, "step-1", 10, "task-10", 123, "planner", "Plan", "Plan it", 1, started_at)

    async def handler(task):
        return TaskQueueHandlerResult(success=True, log="saved")

    queue = TaskQueue(handler, session_factory=_session_factory)
    await queue._record_result(task, await queue._run_handler(task))

    assert FakeAssignedTaskDAO.logs[0]["attempt_no"] == 3
    assert FakeAssignedTaskDAO.logs[0]["status"] == "success"
    assert FakeAssignedTaskDAO.logs[0]["log"] == "saved"
    assert FakeAssignedTaskDAO.cleared == [{"step_db_id": 1}]


@pytest.mark.asyncio
async def test_task_queue_records_failure_retry(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.failed_count = 2
    started_at = datetime.now(timezone.utc)
    task = TaskQueueStep(1, "step-1", 10, "task-10", 123, "planner", "Plan", "Plan it", 1, started_at)

    async def handler(task):
        return TaskQueueHandlerResult(success=False, log="failed")

    queue = TaskQueue(handler, session_factory=_session_factory)
    await queue._record_result(task, await queue._run_handler(task))

    assert FakeAssignedTaskDAO.logs[0]["attempt_no"] == 3
    assert FakeAssignedTaskDAO.logs[0]["status"] == "failed"
    assert FakeAssignedTaskDAO.cleared[0]["step_db_id"] == 1
    assert FakeAssignedTaskDAO.cleared[0]["next_run_at"] - FakeAssignedTaskDAO.logs[0]["finished_at"] == timedelta(minutes=5)


def test_task_queue_retry_delay_schedule():
    assert _retry_delay(1) == timedelta(seconds=30)
    assert _retry_delay(2) == timedelta(seconds=60)
    assert _retry_delay(3) == timedelta(minutes=5)
    assert _retry_delay(4) == timedelta(minutes=10)
    assert _retry_delay(5) == timedelta(minutes=30)
    assert _retry_delay(6) == timedelta(minutes=60)
