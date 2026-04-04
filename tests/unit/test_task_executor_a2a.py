from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from db.dto.task_dto import Task
from db.types import Priority, TaskStatus
from scheduler.task_executor import AgentToAgentTaskExecutor, TaskExecutor


async def _empty_chunk_stream():
    if False:
        yield None


def _make_task() -> Task:
    return Task(
        id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        parent_task_id=None,
        task_type="agent_to_agent",
        status=TaskStatus.pending,
        priority=Priority.normal,
        payload={
            "task_execution_type": "agent_to_agent",
            "goal": "幫用戶整理會議摘要",
            "instruction": "請整理今朝會議重點",
            "callback": {"channel": "whatsapp", "target": "+85290000000", "reply_context": {"instance_id": "85260000"}},
            "requester_agent_id": str(uuid4()),
            "acceptance_mode": "manager_llm_review",
        },
        result=None,
        error_message=None,
        retry_count=0,
        max_retries=3,
        session_id=None,
    )


@pytest.mark.asyncio
async def test_task_executor_dispatches_agent_to_agent_tasks(monkeypatch):
    task = _make_task()
    execute_mock = AsyncMock(return_value={"success": True})

    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor.execute", execute_mock)
    monkeypatch.setattr("scheduler.task_executor.AgentInstanceDAO.claim_agent_for_task", AsyncMock(return_value=True))
    monkeypatch.setattr("scheduler.task_executor.AgentInstanceDAO.release_agent", AsyncMock(return_value=True))

    result = await TaskExecutor.execute_task(task)

    assert result == {"success": True}
    execute_mock.assert_awaited_once_with(task)


@pytest.mark.asyncio
async def test_agent_to_agent_executor_runs_worker_review_and_callback(monkeypatch):
    task = _make_task()
    sender_agent_id = uuid4()
    task.payload["requester_agent_id"] = str(sender_agent_id)

    sender = SimpleNamespace(id=sender_agent_id, user_id=task.user_id, agent_id="agent-sender", name="管家")
    worker = SimpleNamespace(id=uuid4(), user_id=task.user_id, agent_id="agent-worker", name="細𡃁")
    session = SimpleNamespace(session_id="session-private")

    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._get_sender_agent",
        AsyncMock(return_value=sender),
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._select_sub_agent",
        AsyncMock(return_value=worker),
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._get_or_create_private_session",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._run_worker_task",
        AsyncMock(return_value={"output": "worker result", "session_id": session.session_id}),
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._review_worker_result",
        AsyncMock(return_value={"accepted": True, "reason": "ok", "response": "最後答案"}),
    )
    callback_mock = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._dispatch_callback",
        callback_mock,
    )

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is True
    assert result["session_id"] == "session-private"
    assert result["manager_verdict"] == "accepted"
    callback_mock.assert_awaited_once_with(task.payload["callback"], "最後答案")


@pytest.mark.asyncio
async def test_agent_to_agent_executor_dispatches_callback_even_when_review_rejects(monkeypatch):
    task = _make_task()
    sender_agent_id = uuid4()
    task.payload["requester_agent_id"] = str(sender_agent_id)

    sender = SimpleNamespace(id=sender_agent_id, user_id=task.user_id, agent_id="agent-sender", name="管家")
    worker = SimpleNamespace(id=uuid4(), user_id=task.user_id, agent_id="agent-worker", name="細𡃁")
    session = SimpleNamespace(session_id="session-private")

    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._get_sender_agent", AsyncMock(return_value=sender))
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._select_sub_agent", AsyncMock(return_value=worker))
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._get_or_create_private_session", AsyncMock(return_value=session))
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._run_worker_task",
        AsyncMock(return_value={"output": "worker result", "session_id": session.session_id}),
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._review_worker_result",
        AsyncMock(return_value={"accepted": False, "reason": "needs polish", "response": "fallback reply"}),
    )
    callback_mock = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._dispatch_callback", callback_mock)

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is False
    assert result["manager_verdict"] == "rejected"
    callback_mock.assert_awaited_once_with(task.payload["callback"], "fallback reply")


@pytest.mark.asyncio
async def test_agent_to_agent_executor_falls_back_to_worker_output_when_review_errors(monkeypatch):
    task = _make_task()
    sender_agent_id = uuid4()
    task.payload["requester_agent_id"] = str(sender_agent_id)

    sender = SimpleNamespace(id=sender_agent_id, user_id=task.user_id, agent_id="agent-sender", name="管家")
    worker = SimpleNamespace(id=uuid4(), user_id=task.user_id, agent_id="agent-worker", name="細𡃁")
    session = SimpleNamespace(session_id="session-private")

    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._get_sender_agent", AsyncMock(return_value=sender))
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._select_sub_agent", AsyncMock(return_value=worker))
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._get_or_create_private_session", AsyncMock(return_value=session))
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._run_worker_task",
        AsyncMock(return_value={"output": "worker result", "session_id": session.session_id}),
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._review_worker_result",
        AsyncMock(side_effect=RuntimeError("review failed")),
    )
    callback_mock = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._dispatch_callback", callback_mock)

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is False
    assert result["manager_verdict"] == "rejected"
    assert "review failed" in result["manager_reason"]
    callback_mock.assert_awaited_once_with(task.payload["callback"], "worker result")


@pytest.mark.asyncio
async def test_agent_to_agent_review_creates_review_session_before_loading_agent(monkeypatch):
    task = _make_task()
    sender_agent_id = uuid4()
    task.payload["requester_agent_id"] = str(sender_agent_id)

    sender = SimpleNamespace(id=sender_agent_id, user_id=task.user_id, agent_id="agent-sender", name="管家")
    create_session = AsyncMock(return_value=SimpleNamespace(session_id="review-a2a-fixed"))
    get_agent = AsyncMock(return_value=SimpleNamespace(get_memory_prompt=AsyncMock(return_value="memory"), agent_id="agent-sender"))

    monkeypatch.setattr("db.dao.collaboration_session_dao.CollaborationSessionDAO.create", create_session)
    monkeypatch.setattr("agent.bulter.Bulter.get_agent", get_agent)
    monkeypatch.setattr("msg_queue.handler.MsgQueueHandler.create_msg_queue", lambda **_kwargs: _empty_chunk_stream())

    review_result = await AgentToAgentTaskExecutor._review_worker_result(
        sender=sender,
        task=task,
        worker_result={"output": "worker output"},
    )

    create_session.assert_awaited_once()
    created_dto = create_session.await_args.args[0]
    assert created_dto.session_id.startswith("review-a2a-")
    get_agent.assert_awaited_once_with("agent-sender", created_dto.session_id)
    assert review_result["accepted"] is False


@pytest.mark.asyncio
async def test_agent_to_agent_executor_creates_fresh_private_session(monkeypatch):
    task = _make_task()
    sender = SimpleNamespace(id=uuid4(), user_id=task.user_id, name="管家")
    worker = SimpleNamespace(id=uuid4(), name="細𡃁")
    create_session = AsyncMock(return_value=SimpleNamespace(session_id="session-new"))

    monkeypatch.setattr("db.dao.collaboration_session_dao.CollaborationSessionDAO.create", create_session)

    session = await AgentToAgentTaskExecutor._get_or_create_private_session(sender=sender, worker=worker)

    assert session.session_id == "session-new"
    create_session.assert_awaited_once()
