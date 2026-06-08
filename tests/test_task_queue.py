from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.llm.types import StreamChunk
from backend.queues.message_queue import TaskState
from backend.queues.task_queue import (
    TaskQueue,
    TaskQueueHandlerResult,
    TaskQueueStep,
    TaskQueueStepStatus,
)
from backend.queues.task_queue_handle import (
    handle_assigned_task_init_message_step,
    handle_assigned_task_init_step,
    handle_assigned_task_response_step,
    handle_assigned_task_send_step,
)

TASK_CREATE_DT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FakeSession:
    commits = 0
    step_status = "pending"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        type(self).commits += 1

    async def get(self, model, id_):
        return SimpleNamespace(id=id_, status=type(self).step_status)


class FakeAssignedTaskDAO:
    rows = []
    list_calls = []
    processing_marks = []
    processing_mark_result = True
    logs = []
    finished_logs = []
    task_session_updates = []
    step_updates = []
    process_count = 0
    next_log_id = 100

    def __init__(self, session):
        self.session = session

    async def list_due_pending_steps(self, *, now, limit):
        type(self).list_calls.append({"now": now, "limit": limit})
        return type(self).rows[:limit]

    async def mark_step_processing(self, *, step_db_id, now):
        type(self).processing_marks.append({"step_db_id": step_db_id, "now": now})
        return type(self).processing_mark_result

    async def count_process_logs(self, *, step_db_id):
        return type(self).process_count

    async def create_process_log(self, **kwargs):
        type(self).logs.append(kwargs)
        log = SimpleNamespace(id=type(self).next_log_id)
        type(self).next_log_id += 1
        return log

    async def finish_process_log(self, **kwargs):
        type(self).finished_logs.append(kwargs)

    async def update_task_session(self, **kwargs):
        type(self).task_session_updates.append(kwargs)

    async def update_step_assignment_and_session(self, **kwargs):
        type(self).step_updates.append(kwargs)


class FakeAgentDAO:
    agent = SimpleNamespace(id=456, agent_id="agent-assigned")
    responsible_agent = SimpleNamespace(
        id=123,
        agent_id="agent-main",
        whatsapp_instance="main-instance",
        whatsapp_key="main-key",
    )
    by_agent_id = {"agent-assigned": agent}
    find_calls = []

    def __init__(self, session):
        self.session = session

    async def get_first_active_sub_agent_by_user_and_type(self, **kwargs):
        type(self).find_calls.append(kwargs)
        return type(self).agent

    async def get_by_agent_id(self, agent_id):
        return type(self).by_agent_id.get(agent_id)

    async def get_by_id(self, id_):
        if id_ == type(self).responsible_agent.id:
            return type(self).responsible_agent
        if id_ == type(self).agent.id:
            return type(self).agent
        return None


class FakeUserAccDAO:
    user = SimpleNamespace(id=999, phoneno="85298765432")

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, id_):
        if id_ == type(self).user.id:
            return type(self).user
        return None


class FakeEvolutionWhatsAppChannel:
    sent = []

    def __init__(self, whatsapp_instance=None, whatsapp_key=None, **kwargs):
        self.whatsapp_instance = whatsapp_instance
        self.whatsapp_key = whatsapp_key

    async def send_text(self, number, text):
        type(self).sent.append(
            {
                "kind": "text",
                "instance": self.whatsapp_instance,
                "key": self.whatsapp_key,
                "number": number,
                "text": text,
            }
        )
        return {"key": {"id": "interrupt-msg-1"}}

    async def send_document(self, number, media, **options):
        type(self).sent.append(
            {
                "kind": "document",
                "instance": self.whatsapp_instance,
                "key": self.whatsapp_key,
                "number": number,
                "media": media,
                "options": options,
            }
        )
        return {"key": {"id": "document-msg-1"}}

    async def close(self):
        return None


class FakeMsgTask:
    def __init__(self, chunks):
        self.chunks = chunks
        self.acks = []
        self.task_state = TaskState.PENDING

    def stream_gen(self):
        async def gen():
            for chunk in self.chunks:
                yield chunk
            self.task_state = TaskState.COMPLETED

        return gen()

    def ack_stream_callback(self, result):
        self.acks.append(result)


class FakeMessageQueue:
    chunks = []
    created = []
    task = None

    @classmethod
    def instance(cls):
        return cls()

    async def create(self, **kwargs):
        type(self).created.append(kwargs)
        type(self).task = FakeMsgTask(type(self).chunks)
        return type(self).task


class FakeAgentSessionDAO:
    default_session = SimpleNamespace(id=321, session_id="default-main")
    by_session_id = {"step-session-abc": SimpleNamespace(id=654)}
    created_sessions = []
    default_calls = []
    session_id_calls = []

    def __init__(self, session):
        self.session = session

    async def get_default_session_by_agent_db_id(self, agent_db_id):
        type(self).default_calls.append(agent_db_id)
        return type(self).default_session

    async def get_by_session_id(self, session_id):
        type(self).session_id_calls.append(session_id)
        return type(self).by_session_id.get(session_id)

    async def create(self, data):
        session = SimpleNamespace(
            id=654,
            session_id=data.session_id,
            name=data.name,
            recv_agent_id=data.recv_agent_id,
            sender_agent_id=data.sender_agent_id,
            session_type=data.session_type,
        )
        type(self).created_sessions.append(session)
        return session


class FakeAgentMsgHistDAO:
    history_count = 0
    count_calls = []

    def __init__(self, session):
        self.session = session

    async def count_by_session_id(self, session_id):
        type(self).count_calls.append(session_id)
        return type(self).history_count


def _session_factory():
    return FakeSession()


def _step(step_db_id: int, task_db_id: int = 10):
    responsible_agent = SimpleNamespace(id=123, agent_id="agent-main")
    assign_agent = SimpleNamespace(id=456, agent_id="agent-assigned")
    task_session = SimpleNamespace(session_id="task-session-abc")
    step_session = SimpleNamespace(session_id="step-session-abc")
    return SimpleNamespace(
        id=step_db_id,
        step_id=f"step-{step_db_id}",
        task_id=task_db_id,
        task=SimpleNamespace(
            task_id=f"task-{task_db_id}",
            task_name="Build task tracker",
            goal="Build a reliable task tracker for the product team",
            create_dt=TASK_CREATE_DT,
            user_id=999,
            responsible_agent=responsible_agent,
            session=task_session,
        ),
        agent_type="brainstormer",
        agent_type_id=789,
        title="Brainstorm",
        goal="Collect requirements",
        seq_no=1,
        assign_agent_id=assign_agent.id,
        assign_agent=assign_agent,
        session=step_session,
    )


def _task(
    *,
    status: TaskQueueStepStatus = TaskQueueStepStatus.INIT,
    responsible_agent_id: str = "agent-main",
    step_db_id: int = 1,
):
    return TaskQueueStep(
        step_db_id=step_db_id,
        step_id=f"step-{step_db_id}",
        task_db_id=10,
        task_id="task-10",
        task_name="Build task tracker",
        task_goal="Build a reliable task tracker for the product team",
        task_create_dt=TASK_CREATE_DT,
        title="Plan",
        goal="Plan it",
        seq_no=1,
        started_at=datetime.now(timezone.utc),
        agent_type="planner",
        responsible_agent_id=responsible_agent_id,
        user_db_id=999,
        responsible_agent_db_id=123,
        agent_type_db_id=789,
        status=status,
    )


def _queue(handlers=None):
    return TaskQueue(handlers or {}, session_factory=_session_factory)


def _reset_fakes():
    FakeSession.commits = 0
    FakeSession.step_status = "pending"
    FakeAssignedTaskDAO.rows = []
    FakeAssignedTaskDAO.list_calls = []
    FakeAssignedTaskDAO.processing_marks = []
    FakeAssignedTaskDAO.processing_mark_result = True
    FakeAssignedTaskDAO.logs = []
    FakeAssignedTaskDAO.finished_logs = []
    FakeAssignedTaskDAO.task_session_updates = []
    FakeAssignedTaskDAO.step_updates = []
    FakeAssignedTaskDAO.process_count = 0
    FakeAssignedTaskDAO.next_log_id = 100
    FakeAgentDAO.agent = SimpleNamespace(id=456, agent_id="agent-assigned")
    FakeAgentDAO.responsible_agent = SimpleNamespace(
        id=123,
        agent_id="agent-main",
        whatsapp_instance="main-instance",
        whatsapp_key="main-key",
    )
    FakeAgentDAO.by_agent_id = {"agent-assigned": FakeAgentDAO.agent}
    FakeAgentDAO.find_calls = []
    FakeUserAccDAO.user = SimpleNamespace(id=999, phoneno="85298765432")
    FakeEvolutionWhatsAppChannel.sent = []
    FakeMessageQueue.chunks = []
    FakeMessageQueue.created = []
    FakeMessageQueue.task = None
    FakeAgentSessionDAO.default_session = SimpleNamespace(
        id=321, session_id="default-main"
    )
    FakeAgentSessionDAO.by_session_id = {"step-session-abc": SimpleNamespace(id=654)}
    FakeAgentSessionDAO.created_sessions = []
    FakeAgentSessionDAO.default_calls = []
    FakeAgentSessionDAO.session_id_calls = []
    FakeAgentMsgHistDAO.history_count = 0
    FakeAgentMsgHistDAO.count_calls = []


@pytest.mark.asyncio
async def test_task_queue_enqueues_due_pending_step_without_marking_processing(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123)]

    queue = _queue()
    await queue._enqueue_due_steps()

    _, _, queued = await queue._queue.get()
    assert queued.step_db_id == 1
    assert queued.task_name == "Build task tracker"
    assert queued.task_goal == "Build a reliable task tracker for the product team"
    assert queued.task_create_dt == TASK_CREATE_DT
    assert queued.agent_type == "brainstormer"
    assert queued.responsible_agent_id == "agent-main"
    assert queued.user_db_id == 999
    assert queued.responsible_agent_db_id == 123
    assert queued.agent_type_db_id == 789
    assert queued.assign_agent_db_id == 456
    assert queued.task_session_id == "task-session-abc"
    assert queued.step_session_id == "step-session-abc"
    assert queued.assign_agent_id == "agent-assigned"
    assert queued.status == TaskQueueStepStatus.INIT
    assert queue._queued_step_ids == {1}
    assert FakeAssignedTaskDAO.list_calls[0]["limit"] == 4
    assert FakeAssignedTaskDAO.processing_marks == []


@pytest.mark.asyncio
async def test_task_queue_skips_step_already_tracked_in_memory(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123)]

    queue = _queue()
    queue._queued_step_ids.add(1)
    await queue._enqueue_due_steps()

    assert queue._queue.qsize() == 0
    assert queue._queued_step_ids == {1}
    assert FakeAssignedTaskDAO.list_calls[0]["limit"] == 5


@pytest.mark.asyncio
async def test_task_queue_marks_processing_before_first_handler(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)

    calls = []

    async def init_handler(task):
        calls.append(task.status)
        task.status = TaskQueueStepStatus.COMPLETED
        return TaskQueueHandlerResult(success=True, log="done")

    queue = _queue({TaskQueueStepStatus.INIT: init_handler})
    task = _task(status=TaskQueueStepStatus.INIT)

    assert await queue._handle_task(task) is True

    assert calls == [TaskQueueStepStatus.INIT]
    assert FakeAssignedTaskDAO.processing_marks == [
        {"step_db_id": 1, "now": task.started_at}
    ]


@pytest.mark.asyncio
async def test_task_queue_skips_handler_when_processing_mark_fails(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.processing_mark_result = False
    calls = []

    async def init_handler(task):
        calls.append(task.status)
        return None

    queue = _queue({TaskQueueStepStatus.INIT: init_handler})
    task = _task(status=TaskQueueStepStatus.INIT)

    assert await queue._handle_task(task) is True
    assert calls == []
    assert task.process_log_db_id is None
    assert FakeAssignedTaskDAO.processing_marks == [
        {"step_db_id": 1, "now": task.started_at}
    ]


@pytest.mark.asyncio
async def test_task_queue_enqueues_same_agent_steps_and_worker_gate_decides(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)
    FakeAssignedTaskDAO.rows = [(_step(1), 123), (_step(2), 123)]

    queue = TaskQueue({}, max_concurrency=4, session_factory=_session_factory)
    await queue._enqueue_due_steps()

    assert queue._queue.qsize() == 2
    task = _task(responsible_agent_id="agent-main")
    queue._active_responsible_agent_ids.add("agent-main")
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
    send_task = _task(status=TaskQueueStepStatus.SEND, step_db_id=2)

    assert await queue._handle_task(init_task) is True
    assert await queue._handle_task(send_task) is False
    assert calls == [TaskQueueStepStatus.INIT]


@pytest.mark.asyncio
async def test_task_queue_active_agent_blocks_same_agent_steps(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)

    queue = _queue()
    queue._active_responsible_agent_ids.add("agent-main")

    send_task = _task(status=TaskQueueStepStatus.SEND, responsible_agent_id="agent-main")
    init_message_task = _task(
        status=TaskQueueStepStatus.INIT_MESSAGE, responsible_agent_id="agent-main"
    )
    response_task = _task(
        status=TaskQueueStepStatus.RESPONSE, responsible_agent_id="agent-main"
    )
    init_task = _task(status=TaskQueueStepStatus.INIT, responsible_agent_id="agent-main")

    assert await queue._handle_task(send_task) is False
    assert await queue._handle_task(init_message_task) is False
    assert await queue._handle_task(response_task) is False
    assert await queue._handle_task(init_task) is False


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
async def test_task_queue_failed_handler_finishes_process_log(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue.AssignedTaskDAO", FakeAssignedTaskDAO)

    async def init_handler(task):
        raise RuntimeError("handler failed")

    queue = _queue({TaskQueueStepStatus.INIT: init_handler})
    task = _task(status=TaskQueueStepStatus.INIT)

    assert await queue._handle_task(task) is True
    assert FakeAssignedTaskDAO.finished_logs[0]["status"] == "failed"
    assert FakeAssignedTaskDAO.finished_logs[0]["log"] == "handler failed"


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
        TaskQueueStepStatus.INIT_MESSAGE,
        TaskQueueStepStatus.SEND,
        TaskQueueStepStatus.RESPONSE,
        TaskQueueStepStatus.COMPLETED,
    ):
        await queue._enqueue_task(_task(status=status))

    ordered = []
    while not queue._queue.empty():
        _, _, task = await queue._queue.get()
        ordered.append(task.status)

    assert ordered == [
        TaskQueueStepStatus.COMPLETED,
        TaskQueueStepStatus.RESPONSE,
        TaskQueueStepStatus.SEND,
        TaskQueueStepStatus.INIT_MESSAGE,
        TaskQueueStepStatus.INIT,
    ]


@pytest.mark.asyncio
async def test_assigned_task_init_step_initializes_assignment_and_sessions(
    monkeypatch, caplog
):
    _reset_fakes()
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr("backend.queues.task_queue_handle.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentSessionDAO", FakeAgentSessionDAO
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AssignedTaskDAO", FakeAssignedTaskDAO
    )
    caplog.set_level(logging.INFO, logger="backend.queues.task_queue_handle")

    init_task = _task(status=TaskQueueStepStatus.INIT)
    init_result = await handle_assigned_task_init_step(init_task)
    assert init_result is None
    assert init_task.status == TaskQueueStepStatus.INIT_MESSAGE
    assert init_task.assign_agent_id == "agent-assigned"
    assert init_task.assign_agent_db_id == 456
    assert init_task.task_session_id == "default-main"
    assert init_task.step_session_id.startswith("session-")
    assert FakeAgentDAO.find_calls == [{"user_id": 999, "agent_type_id": 789}]
    assert FakeAgentSessionDAO.default_calls == [123]
    assert FakeAssignedTaskDAO.task_session_updates == [
        {"task_db_id": 10, "session_db_id": 321}
    ]
    assert FakeAssignedTaskDAO.step_updates == [
        {"step_db_id": 1, "assign_agent_db_id": 456},
        {"step_db_id": 1, "session_db_id": 654},
    ]
    assert FakeAgentSessionDAO.created_sessions[0].recv_agent_id == 456
    assert FakeAgentSessionDAO.created_sessions[0].sender_agent_id == 123
    assert FakeAgentSessionDAO.created_sessions[0].session_type == "chat"
    assert "status=init" in caplog.text
    assert "responsible_agent_id=agent-main" in caplog.text
    assert "assign_agent_id=None" in caplog.text
    assert "task_session_id=" in caplog.text
    assert "step_session_id=" in caplog.text
    assert "task_name=Build task tracker" in caplog.text
    assert "step_name=Plan" in caplog.text


@pytest.mark.asyncio
async def test_assigned_task_init_step_reuses_existing_assignment_and_sessions(
    monkeypatch,
):
    _reset_fakes()
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr("backend.queues.task_queue_handle.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentSessionDAO", FakeAgentSessionDAO
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AssignedTaskDAO", FakeAssignedTaskDAO
    )

    task = _task(status=TaskQueueStepStatus.INIT)
    task.assign_agent_id = "agent-assigned"
    task.assign_agent_db_id = 456
    task.task_session_id = "task-session-abc"
    task.step_session_id = "step-session-abc"

    result = await handle_assigned_task_init_step(task)

    assert result is None
    assert task.status == TaskQueueStepStatus.INIT_MESSAGE
    assert FakeAgentDAO.find_calls == []
    assert FakeAgentSessionDAO.default_calls == []
    assert FakeAgentSessionDAO.created_sessions == []
    assert FakeAssignedTaskDAO.task_session_updates == []
    assert FakeAssignedTaskDAO.step_updates == []


@pytest.mark.asyncio
async def test_assigned_task_init_step_raises_when_sub_agent_missing(monkeypatch):
    _reset_fakes()
    FakeAgentDAO.agent = None
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr("backend.queues.task_queue_handle.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentSessionDAO", FakeAgentSessionDAO
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AssignedTaskDAO", FakeAssignedTaskDAO
    )

    with pytest.raises(LookupError):
        await handle_assigned_task_init_step(_task(status=TaskQueueStepStatus.INIT))


@pytest.mark.asyncio
async def test_assigned_task_init_message_step_prepares_initial_message(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentSessionDAO", FakeAgentSessionDAO
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentMsgHistDAO", FakeAgentMsgHistDAO
    )
    init_message_task = _task(status=TaskQueueStepStatus.INIT_MESSAGE)
    init_message_task.step_session_id = "step-session-abc"

    init_message_result = await handle_assigned_task_init_message_step(init_message_task)

    assert init_message_result is None
    assert init_message_task.status == TaskQueueStepStatus.SEND
    assert init_message_task.message == (
        "請開始處理以下 assigned task step。\n\n"
        "任務名稱：Build task tracker\n"
        "任務目標：\n"
        "Build a reliable task tracker for the product team\n\n"
        "Session 目標：\n"
        "Plan it\n\n"
        "請專注完成這個 session 的目標，並在需要時提出明確問題或交付可供下一步使用的結果。"
    )
    assert "task-10" not in init_message_task.message
    assert "step-1" not in init_message_task.message
    assert FakeAgentSessionDAO.session_id_calls == ["step-session-abc"]
    assert FakeAgentMsgHistDAO.count_calls == [654]


@pytest.mark.asyncio
async def test_assigned_task_init_message_step_prepares_continue_message(monkeypatch):
    _reset_fakes()
    FakeAgentMsgHistDAO.history_count = 2
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentSessionDAO", FakeAgentSessionDAO
    )
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.AgentMsgHistDAO", FakeAgentMsgHistDAO
    )
    init_message_task = _task(status=TaskQueueStepStatus.INIT_MESSAGE)
    init_message_task.step_session_id = "step-session-abc"

    init_message_result = await handle_assigned_task_init_message_step(init_message_task)

    assert init_message_result is None
    assert init_message_task.status == TaskQueueStepStatus.SEND
    assert init_message_task.message == (
        "請繼續處理之前的任務動作。"
        "請根據這個 session 之前的對話及已完成內容繼續推進。"
    )
    assert "Build task tracker" not in init_message_task.message
    assert "task-10" not in init_message_task.message
    assert "step-1" not in init_message_task.message
    assert FakeAgentSessionDAO.session_id_calls == ["step-session-abc"]
    assert FakeAgentMsgHistDAO.count_calls == [654]


@pytest.mark.asyncio
async def test_assigned_task_send_response_handler_completes(
    monkeypatch, caplog
):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue_handle.MessageQueue", FakeMessageQueue)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    FakeMessageQueue.chunks = [
        SimpleNamespace(chunk_type="content", content="done", data=None)
    ]

    caplog.set_level(logging.INFO, logger="backend.queues.task_queue_handle")
    send_task = _task(status=TaskQueueStepStatus.SEND)
    send_task.assign_agent_id = "agent-assigned"
    send_task.step_session_id = "step-session-abc"

    caplog.clear()
    send_result = await handle_assigned_task_send_step(send_task)
    assert send_result is None
    assert send_task.status == TaskQueueStepStatus.RESPONSE
    assert send_task.message == "done"
    assert FakeMessageQueue.created == [
        {
            "agent_id": "agent-assigned",
            "session_id": "step-session-abc",
            "message": "",
        }
    ]
    assert "status=send" in caplog.text

    caplog.clear()
    response_task = _task(status=TaskQueueStepStatus.RESPONSE)
    response_result = await handle_assigned_task_response_step(response_task)
    assert response_result is not None
    assert response_result.success is True
    assert response_task.status == TaskQueueStepStatus.COMPLETED
    assert "status=response" in caplog.text


@pytest.mark.asyncio
async def test_assigned_task_send_completes_when_db_step_already_completed(
    monkeypatch,
):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue_handle.MessageQueue", FakeMessageQueue)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    FakeSession.step_status = "completed"
    FakeMessageQueue.chunks = [
        SimpleNamespace(chunk_type="content", content="approved", data=None)
    ]

    send_task = _task(status=TaskQueueStepStatus.SEND)
    send_task.assign_agent_id = "agent-assigned"
    send_task.step_session_id = "step-session-abc"

    send_result = await handle_assigned_task_send_step(send_task)

    assert send_result is not None
    assert send_result.success is True
    assert send_task.status == TaskQueueStepStatus.COMPLETED
    assert send_task.message == ""


@pytest.mark.asyncio
async def test_assigned_task_send_interrupt_sends_whatsapp_and_completes(
    monkeypatch,
):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue_handle.MessageQueue", FakeMessageQueue)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr("backend.queues.task_queue_handle.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr("backend.queues.task_queue_handle.UserAccDAO", FakeUserAccDAO)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.EvolutionWhatsAppChannel",
        FakeEvolutionWhatsAppChannel,
    )
    FakeMessageQueue.chunks = [
        SimpleNamespace(
            chunk_type="interrupt",
            content=None,
            data={"message": "請確認任務"},
        )
    ]

    send_task = _task(status=TaskQueueStepStatus.SEND)
    send_task.assign_agent_id = "agent-assigned"
    send_task.step_session_id = "step-session-abc"

    send_result = await handle_assigned_task_send_step(send_task)

    assert send_result is not None
    assert send_result.success is True
    assert send_task.status == TaskQueueStepStatus.COMPLETED
    assert FakeEvolutionWhatsAppChannel.sent == [
        {
            "kind": "text",
            "instance": "main-instance",
            "key": "main-key",
            "number": "85298765432",
            "text": "請確認任務",
        }
    ]
    assert FakeMessageQueue.task.acks == ["interrupt-msg-1"]


@pytest.mark.asyncio
async def test_assigned_task_send_interrupt_sends_whatsapp_document(
    monkeypatch,
):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue_handle.MessageQueue", FakeMessageQueue)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr("backend.queues.task_queue_handle.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr("backend.queues.task_queue_handle.UserAccDAO", FakeUserAccDAO)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.EvolutionWhatsAppChannel",
        FakeEvolutionWhatsAppChannel,
    )
    FakeMessageQueue.chunks = [
        StreamChunk(
            chunk_type="interrupt",
            data={
                "message": "請查看附件 HTML 計劃書。",
                "whatsapp_document": {
                    "media": "PGh0bWw+PC9odG1sPg==",
                    "mimetype": "text/html",
                    "file_name": "計劃書.html",
                    "caption": "請查看附件 HTML 計劃書。",
                },
            },
        )
    ]

    send_task = _task(status=TaskQueueStepStatus.SEND)
    send_task.assign_agent_id = "agent-assigned"
    send_task.step_session_id = "step-session-abc"

    send_result = await handle_assigned_task_send_step(send_task)

    assert send_result is not None
    assert send_result.success is True
    assert send_task.status == TaskQueueStepStatus.COMPLETED
    assert FakeEvolutionWhatsAppChannel.sent == [
        {
            "kind": "document",
            "instance": "main-instance",
            "key": "main-key",
            "number": "85298765432",
            "media": "PGh0bWw+PC9odG1sPg==",
            "options": {
                "mimetype": "text/html",
                "file_name": "計劃書.html",
                "caption": "請查看附件 HTML 計劃書。",
            },
        }
    ]
    assert FakeMessageQueue.task.acks == ["document-msg-1"]


@pytest.mark.asyncio
async def test_assigned_task_send_interrupt_missing_whatsapp_data_sends_nothing(
    monkeypatch,
):
    _reset_fakes()
    monkeypatch.setattr("backend.queues.task_queue_handle.MessageQueue", FakeMessageQueue)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.async_session_factory", _session_factory
    )
    monkeypatch.setattr("backend.queues.task_queue_handle.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr("backend.queues.task_queue_handle.UserAccDAO", FakeUserAccDAO)
    monkeypatch.setattr(
        "backend.queues.task_queue_handle.EvolutionWhatsAppChannel",
        FakeEvolutionWhatsAppChannel,
    )
    FakeAgentDAO.responsible_agent = SimpleNamespace(
        id=123,
        agent_id="agent-main",
        whatsapp_instance=None,
        whatsapp_key="main-key",
    )
    FakeMessageQueue.chunks = [
        SimpleNamespace(
            chunk_type="interrupt",
            content="fallback approval",
            data={},
        )
    ]

    send_task = _task(status=TaskQueueStepStatus.SEND)
    send_task.assign_agent_id = "agent-assigned"
    send_task.step_session_id = "step-session-abc"

    send_result = await handle_assigned_task_send_step(send_task)

    assert send_result is not None
    assert send_result.success is True
    assert send_task.status == TaskQueueStepStatus.COMPLETED
    assert FakeEvolutionWhatsAppChannel.sent == []
    assert FakeMessageQueue.task.acks == []


def test_task_queue_step_change_status():
    task = _task(status=TaskQueueStepStatus.INIT)

    task.change_status(TaskQueueStepStatus.RESPONSE)

    assert task.status == TaskQueueStepStatus.RESPONSE
