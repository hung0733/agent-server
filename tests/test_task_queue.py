from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.queues.task_queue import (
    TaskQueue,
    TaskQueueHandlerResult,
    TaskQueueStep,
    TaskQueueStepStatus,
)
from backend.queues.task_queue_handle import (
    handle_assigned_task_init_step,
    handle_assigned_task_resume_step,
    handle_assigned_task_send_step,
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
    list_calls = []
    logs = []
    finished_logs = []
    process_count = 0
    next_log_id = 100

    def __init__(self, session):
        self.session = session

    async def list_due_pending_steps(self, *, now, limit):
        type(self).list_calls.append({"now": now, "limit": limit})
        return type(self).rows[:limit]

    async def count_process_logs(self, *, step_db_id):
        return type(self).process_count

    async def create_process_log(self, **kwargs):
        type(self).logs.append(kwargs)
        log = SimpleNamespace(id=type(self).next_log_id)
        type(self).next_log_id += 1
        return log

    async def finish_process_log(self, **kwargs):
        type(self).finished_logs.append(kwargs)


def _session_factory():
    return FakeSession()


def _step(step_db_id: int, task_db_id: int = 10):
    responsible_agent = SimpleNamespace(id=123, agent_id="agent-main")
    assign_agent = SimpleNamespace(id=456, agent_id="agent-assigned")
    session = SimpleNamespace(session_id="session-abc")
    return SimpleNamespace(
        id=step_db_id,
        step_id=f"step-{step_db_id}",
        task_id=task_db_id,
        task=SimpleNamespace(
            task_id=f"task-{task_db_id}",
            responsible_agent=responsible_agent,
            session=session,
        ),
        agent_type="brainstormer",
        agent_type_id=789,
        title="Brainstorm",
        goal="Collect requirements",
        seq_no=1,
        assign_agent_id=assign_agent.id,
        assign_agent=assign_agent,
        session=None,
    )


def _task(
    *,
    status: TaskQueueStepStatus = TaskQueueStepStatus.INIT,
    responsible_agent_id: int = 123,
    step_db_id: int = 1,
):
    return TaskQueueStep(
        step_db_id,
        f"step-{step_db_id}",
        10,
        "task-10",
        responsible_agent_id,
        "planner",
        "Plan",
        "Plan it",
        1,
        datetime.now(timezone.utc),
        status=status,
    )


def _queue(handlers=None):
    return TaskQueue(handlers or {}, session_factory=_session_factory)


def _reset_fakes():
    FakeSession.commits = 0
    FakeAssignedTaskDAO.rows = []
    FakeAssignedTaskDAO.list_calls = []
    FakeAssignedTaskDAO.logs = []
    FakeAssignedTaskDAO.finished_logs = []
    FakeAssignedTaskDAO.process_count = 0
    FakeAssignedTaskDAO.next_log_id = 100


@pytest.mark.asyncio
async def test_task_queue_enqueues_due_pending_step_without_marking_step(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123)]

    queue = _queue()
    await queue._enqueue_due_steps()

    _, _, queued = await queue._queue.get()
    assert queued.step_db_id == 1
    assert queued.responsible_agent_id == 123
    assert queued.assign_agent_id == 456
    assert queued.agent_type_id == 789
    assert queued.responsible_agent.agent_id == "agent-main"
    assert queued.assign_agent.agent_id == "agent-assigned"
    assert queued.session_id == "session-abc"
    assert queued.status == TaskQueueStepStatus.INIT
    assert queue._queued_step_ids == {1}
    assert FakeAssignedTaskDAO.list_calls[0]["limit"] == 4


@pytest.mark.asyncio
async def test_task_queue_enqueues_same_agent_steps_and_worker_gate_decides(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123), (_step(2), 123)]

    queue = TaskQueue({}, max_concurrency=4, session_factory=_session_factory)
    await queue._enqueue_due_steps()

    assert queue._queue.qsize() == 2
    task = _task(responsible_agent_id=123)
    queue._active_responsible_agent_ids.add(123)
    assert await queue._handle_task(task) is False


@pytest.mark.asyncio
async def test_task_queue_only_calls_registered_status_handler(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    calls = []

    async def init_handler(task):
        calls.append(task.status)
        task.status = TaskQueueStepStatus.COMPLETED
        return TaskQueueHandlerResult(success=True, log="done")

    queue = _queue({TaskQueueStepStatus.INIT: init_handler})
    init_task = _task(status=TaskQueueStepStatus.INIT)
    interrupt_task = _task(status=TaskQueueStepStatus.INTERRUPT, step_db_id=2)

    assert await queue._handle_task(init_task) is True
    assert await queue._handle_task(interrupt_task) is False
    assert calls == [TaskQueueStepStatus.INIT]


@pytest.mark.asyncio
async def test_task_queue_interrupt_blocks_same_agent_send_and_init(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)

    queue = _queue()
    await queue._enqueue_task(
        _task(status=TaskQueueStepStatus.INTERRUPT, responsible_agent_id=123)
    )

    send_task = _task(status=TaskQueueStepStatus.SEND, responsible_agent_id=123)
    init_task = _task(status=TaskQueueStepStatus.INIT, responsible_agent_id=123)
    resume_task = _task(status=TaskQueueStepStatus.RESUME, responsible_agent_id=123)

    assert await queue._handle_task(send_task) is False
    assert await queue._handle_task(init_task) is False
    assert await queue._handle_task(resume_task) is False


@pytest.mark.asyncio
async def test_task_queue_completed_with_result_closes_process_log(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)

    queue = _queue()
    task = _task(status=TaskQueueStepStatus.COMPLETED)
    task.process_log_db_id = 99
    task.handler_result = TaskQueueHandlerResult(success=True, log="saved")

    assert await queue._handle_task(task) is True
    assert FakeAssignedTaskDAO.finished_logs[0]["process_log_db_id"] == 99
    assert FakeAssignedTaskDAO.finished_logs[0]["status"] == "success"
    assert FakeAssignedTaskDAO.finished_logs[0]["log"] == "saved"


@pytest.mark.asyncio
async def test_task_queue_none_result_or_uncompleted_status_stays_in_queue(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)

    async def send_handler(task):
        return None

    queue = _queue({TaskQueueStepStatus.SEND: send_handler})
    task = _task(status=TaskQueueStepStatus.SEND)

    assert await queue._handle_task(task) is False
    assert task.process_log_db_id == 100
    assert FakeAssignedTaskDAO.logs[0]["status"] == "processing"
    assert FakeAssignedTaskDAO.logs[0]["finished_at"] is None
    assert FakeAssignedTaskDAO.finished_logs == []


@pytest.mark.asyncio
async def test_task_queue_priority_order():
    queue = _queue()
    for status in (
        TaskQueueStepStatus.INIT,
        TaskQueueStepStatus.SEND,
        TaskQueueStepStatus.INTERRUPT,
        TaskQueueStepStatus.RESUME,
        TaskQueueStepStatus.COMPLETED,
    ):
        await queue._enqueue_task(_task(status=status))

    ordered = []
    while not queue._queue.empty():
        _, _, task = await queue._queue.get()
        ordered.append(task.status)

    assert ordered == [
        TaskQueueStepStatus.COMPLETED,
        TaskQueueStepStatus.RESUME,
        TaskQueueStepStatus.INTERRUPT,
        TaskQueueStepStatus.SEND,
        TaskQueueStepStatus.INIT,
    ]


@pytest.mark.asyncio
async def test_assigned_task_handlers_are_split_by_status():
    init_task = _task(status=TaskQueueStepStatus.INIT)
    init_result = await handle_assigned_task_init_step(init_task)
    assert init_result is None
    assert init_task.status == TaskQueueStepStatus.SEND

    send_result = await handle_assigned_task_send_step(init_task)
    assert send_result is not None
    assert send_result.success is True
    assert init_task.status == TaskQueueStepStatus.COMPLETED

    resume_task = _task(status=TaskQueueStepStatus.RESUME)
    resume_result = await handle_assigned_task_resume_step(resume_task)
    assert resume_result is not None
    assert resume_result.success is True
    assert resume_task.status == TaskQueueStepStatus.COMPLETED


def test_task_queue_step_change_status():
    task = _task(status=TaskQueueStepStatus.INIT)

    task.change_status(TaskQueueStepStatus.INTERRUPT)

    assert task.status == TaskQueueStepStatus.INTERRUPT
