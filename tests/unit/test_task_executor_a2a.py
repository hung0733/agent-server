from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import logging

import pytest

from db.dto.task_dto import Task
from db.types import Priority, TaskStatus
from scheduler.task_executor import AgentToAgentTaskExecutor, TaskExecutor


async def _empty_chunk_stream():
    if False:
        yield None


async def _tool_chunk_stream():
    yield SimpleNamespace(chunk_type="tool", content="search_web(query='foo')")
    yield SimpleNamespace(chunk_type="tool_result", content="found 3 results")
    yield SimpleNamespace(chunk_type="content", content="done")


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
        AsyncMock(return_value={"verdict": "accept", "reason": "ok", "response": "最後答案"}),
    )
    callback_mock = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._dispatch_callback",
        callback_mock,
    )

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is True
    assert result["session_id"] == "session-private"
    assert result["manager_verdict"] == "accept"
    assert result["revision_count"] == 0
    callback_mock.assert_awaited_once_with(task.payload["callback"], "最後答案")


@pytest.mark.asyncio
async def test_agent_to_agent_executor_revises_worker_in_same_session(monkeypatch):
    task = _make_task()
    sender_agent_id = uuid4()
    task.payload["requester_agent_id"] = str(sender_agent_id)

    sender = SimpleNamespace(id=sender_agent_id, user_id=task.user_id, agent_id="agent-sender", name="管家")
    worker = SimpleNamespace(id=uuid4(), user_id=task.user_id, agent_id="agent-worker", name="細𡃁")
    session = SimpleNamespace(session_id="session-private")

    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._get_sender_agent", AsyncMock(return_value=sender))
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._select_sub_agent", AsyncMock(return_value=worker))
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._get_or_create_private_session", AsyncMock(return_value=session))
    run_worker = AsyncMock(
        side_effect=[
            {"output": "draft v1", "session_id": session.session_id},
            {"output": "draft v2", "session_id": session.session_id},
        ]
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._run_worker_task",
        run_worker,
    )
    monkeypatch.setattr(
        "scheduler.task_executor.AgentToAgentTaskExecutor._review_worker_result",
        AsyncMock(
            side_effect=[
                {"verdict": "revise", "reason": "補充決策時間線", "response": ""},
                {"verdict": "accept", "reason": "ok", "response": "最後答案"},
            ]
        ),
    )
    callback_mock = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._dispatch_callback", callback_mock)

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is True
    assert result["manager_verdict"] == "accept"
    assert result["revision_count"] == 1
    assert run_worker.await_count == 2
    first_call = run_worker.await_args_list[0]
    second_call = run_worker.await_args_list[1]
    assert first_call.kwargs["session_id"] == session.session_id
    assert second_call.kwargs["session_id"] == session.session_id
    assert "補充決策時間線" in second_call.kwargs["task"].payload["instruction"]
    callback_mock.assert_awaited_once_with(task.payload["callback"], "最後答案")


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
    assert result["manager_verdict"] == "fail"
    assert "review failed" in result["manager_reason"]
    callback_mock.assert_awaited_once_with(task.payload["callback"], "worker result")


def test_build_revision_instruction_includes_goal_output_and_feedback():
    prompt = AgentToAgentTaskExecutor._build_revision_instruction(
        goal="幫用戶整理會議摘要",
        instruction="請整理今朝會議重點",
        previous_output="舊答案",
        review_reason="請補回決策時間線",
    )

    assert "[Original Goal]" in prompt
    assert "幫用戶整理會議摘要" in prompt
    assert "[Original Instruction]" in prompt
    assert "請整理今朝會議重點" in prompt
    assert "[Previous Output]" in prompt
    assert "舊答案" in prompt
    assert "[Manager Feedback]" in prompt
    assert "請補回決策時間線" in prompt


@pytest.mark.asyncio
async def test_agent_to_agent_executor_callbacks_once_on_fail(monkeypatch):
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
        AsyncMock(return_value={"verdict": "fail", "reason": "缺少必要資料", "response": "而家資料不足，未能完成。"}),
    )
    callback_mock = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("scheduler.task_executor.AgentToAgentTaskExecutor._dispatch_callback", callback_mock)

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is False
    assert result["manager_verdict"] == "fail"
    callback_mock.assert_awaited_once_with(task.payload["callback"], "而家資料不足，未能完成。")


@pytest.mark.asyncio
async def test_agent_to_agent_executor_accepts_whatsapp_callback_with_instance_id_on_root(monkeypatch):
    task = _make_task()
    sender_agent_id = uuid4()
    task.payload["requester_agent_id"] = str(sender_agent_id)
    task.payload["callback"] = {
        "channel": "whatsapp",
        "target": "+85290000000",
        "instance_id": "85260000",
        "reply_context": {"message_id": "wamid-123"},
    }

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
        AsyncMock(return_value={"verdict": "accept", "reason": "ok", "response": "最後答案"}),
    )
    send_text = AsyncMock(return_value=None)
    monkeypatch.setattr("channels.whatsapp.WhatsAppChannel.send_text", send_text)

    result = await AgentToAgentTaskExecutor.execute(task)

    assert result["success"] is True
    send_text.assert_awaited_once_with("85260000", "85290000000", "最後答案")


@pytest.mark.asyncio
async def test_dispatch_callback_logs_missing_whatsapp_fields(caplog):
    caplog.set_level(logging.WARNING, logger="scheduler.task_executor")

    with pytest.raises(ValueError):
        await AgentToAgentTaskExecutor._dispatch_callback(
            {"channel": "whatsapp", "target": "+85290000000", "reply_context": {}},
            "最後答案",
        )

    assert "whatsapp callback 缺少欄位" in caplog.text
    assert "instance_id=False" in caplog.text


@pytest.mark.asyncio
async def test_run_worker_task_logs_tool_usage(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="scheduler.task_executor")

    monkeypatch.setattr(
        "msg_queue.handler.MsgQueueHandler.create_msg_queue",
        lambda **_kwargs: _tool_chunk_stream(),
    )

    sender = SimpleNamespace(id=uuid4())
    worker = SimpleNamespace(agent_id="agent-worker")
    task = _make_task()

    result = await AgentToAgentTaskExecutor._run_worker_task(
        sender=sender,
        worker=worker,
        session_id="session-private",
        task=task,
    )

    assert result["output"] == "done"
    assert "A2A worker tool call" in caplog.text
    assert "search_web(query='foo')" in caplog.text
    assert "A2A worker tool result" in caplog.text
    assert "found 3 results" in caplog.text


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
        worker_result={"output": "worker output", "session_id": "session-private"},
    )

    create_session.assert_awaited_once()
    created_dto = create_session.await_args.args[0]
    assert created_dto.session_id.startswith("review-a2a-")
    get_agent.assert_awaited_once_with("agent-sender", created_dto.session_id)
    assert review_result["verdict"] == "fail"


@pytest.mark.asyncio
async def test_agent_to_agent_review_returns_verdict_shape(monkeypatch):
    task = _make_task()
    sender = SimpleNamespace(id=uuid4(), user_id=task.user_id, agent_id="agent-sender", name="管家")

    async def _content_chunk_stream():
        yield SimpleNamespace(chunk_type="content", content='{"verdict":"revise","reason":"補充重點","response":""}')

    monkeypatch.setattr(
        "db.dao.collaboration_session_dao.CollaborationSessionDAO.create",
        AsyncMock(return_value=SimpleNamespace(session_id="review-a2a-fixed")),
    )
    monkeypatch.setattr(
        "agent.bulter.Bulter.get_agent",
        AsyncMock(return_value=SimpleNamespace(get_memory_prompt=AsyncMock(return_value="memory"), agent_id="agent-sender")),
    )
    monkeypatch.setattr("msg_queue.handler.MsgQueueHandler.create_msg_queue", lambda **_kwargs: _content_chunk_stream())

    review_result = await AgentToAgentTaskExecutor._review_worker_result(
        sender=sender,
        task=task,
        worker_result={"output": "worker output", "session_id": "session-private"},
    )

    assert review_result == {
        "verdict": "revise",
        "reason": "補充重點",
        "response": "",
    }


@pytest.mark.asyncio
async def test_agent_to_agent_review_invalid_json_returns_fail(monkeypatch):
    task = _make_task()
    sender = SimpleNamespace(id=uuid4(), user_id=task.user_id, agent_id="agent-sender", name="管家")

    async def _content_chunk_stream():
        yield SimpleNamespace(chunk_type="content", content="not-json")

    monkeypatch.setattr(
        "db.dao.collaboration_session_dao.CollaborationSessionDAO.create",
        AsyncMock(return_value=SimpleNamespace(session_id="review-a2a-fixed")),
    )
    monkeypatch.setattr(
        "agent.bulter.Bulter.get_agent",
        AsyncMock(return_value=SimpleNamespace(get_memory_prompt=AsyncMock(return_value="memory"), agent_id="agent-sender")),
    )
    monkeypatch.setattr("msg_queue.handler.MsgQueueHandler.create_msg_queue", lambda **_kwargs: _content_chunk_stream())

    review_result = await AgentToAgentTaskExecutor._review_worker_result(
        sender=sender,
        task=task,
        worker_result={"output": "worker output", "session_id": "session-private"},
    )

    assert review_result["verdict"] == "fail"
    assert "有效 JSON" in review_result["reason"]


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
