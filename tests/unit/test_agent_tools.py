from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from db.types import Priority, TaskStatus
from tools.agent_tools import submit_delegate_task_impl


@pytest.mark.asyncio
async def test_submit_delegate_task_creates_agent_to_agent_task(monkeypatch) -> None:
    caller_id = uuid4()
    user_id = uuid4()
    created_task_id = uuid4()
    callback = {
        "channel": "whatsapp",
        "target": "+85290000000",
        "reply_context": {"message_id": "wamid-123"},
    }

    caller = SimpleNamespace(id=caller_id, user_id=user_id, name="Butler")
    created_task = SimpleNamespace(id=created_task_id)
    created_queue_entry = SimpleNamespace(id=uuid4())

    get_by_id = AsyncMock(return_value=caller)
    create_task = AsyncMock(return_value=created_task)
    create_queue_entry = AsyncMock(return_value=created_queue_entry)

    monkeypatch.setattr("tools.agent_tools.AgentInstanceDAO.get_by_id", get_by_id)
    monkeypatch.setattr("tools.agent_tools.TaskDAO.create", create_task)
    monkeypatch.setattr("tools.agent_tools.TaskQueueDAO.create", create_queue_entry)

    result = await submit_delegate_task_impl(
        goal="幫用戶安排會議摘要",
        instruction="請整理今日會議重點，同埋列出三個 follow-up。",
        callback=callback,
        agent_db_id=str(caller_id),
    )

    create_task.assert_awaited_once()
    create_queue_entry.assert_awaited_once()
    task_create = create_task.await_args.args[0]
    queue_create = create_queue_entry.await_args.args[0]

    assert task_create.user_id == user_id
    assert task_create.agent_id == caller_id
    assert task_create.task_type == "agent_to_agent"
    assert task_create.status == TaskStatus.pending
    assert task_create.priority == Priority.normal
    assert task_create.payload == {
        "task_execution_type": "agent_to_agent",
        "goal": "幫用戶安排會議摘要",
        "instruction": "請整理今日會議重點，同埋列出三個 follow-up。",
        "callback": callback,
        "requester_agent_id": str(caller_id),
        "acceptance_mode": "manager_llm_review",
    }
    assert queue_create.task_id == created_task_id
    assert queue_create.status == TaskStatus.pending
    assert queue_create.priority == 10
    assert str(created_task_id) in result
    assert "已經落單" in result


@pytest.mark.asyncio
async def test_submit_delegate_task_requires_agent_context() -> None:
    result = await submit_delegate_task_impl(
        goal="g",
        instruction="i",
        callback={"channel": "whatsapp"},
        agent_db_id="",
    )

    assert "agent_db_id" in result


@pytest.mark.asyncio
async def test_submit_delegate_task_handles_missing_caller(monkeypatch) -> None:
    get_by_id = AsyncMock(return_value=None)
    create_task = AsyncMock()
    create_queue_entry = AsyncMock()

    monkeypatch.setattr("tools.agent_tools.AgentInstanceDAO.get_by_id", get_by_id)
    monkeypatch.setattr("tools.agent_tools.TaskDAO.create", create_task)
    monkeypatch.setattr("tools.agent_tools.TaskQueueDAO.create", create_queue_entry)

    result = await submit_delegate_task_impl(
        goal="幫用戶安排會議摘要",
        instruction="請整理今日會議重點。",
        callback={"channel": "whatsapp"},
        agent_db_id=str(uuid4()),
    )

    create_task.assert_not_called()
    create_queue_entry.assert_not_called()
    assert "找不到 Agent 實例" in result
