from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import tools.tools as tools_module
from tools.tools import _make_executor


@pytest.mark.asyncio
async def test_make_executor_persists_successful_tool_call(monkeypatch):
    task_id = str(uuid4())
    tool_id = uuid4()
    tool_version_id = uuid4()
    created_tool_call_id = uuid4()

    create_mock = AsyncMock(return_value=SimpleNamespace(id=created_tool_call_id))
    update_mock = AsyncMock()

    monkeypatch.setattr(
        tools_module,
        "ToolCallDAO",
        SimpleNamespace(create=create_mock, update=update_mock),
        raising=False,
    )

    executor = _make_executor(
        implementation_ref="tests.unit.simple_tool_module:successful_tool",
        merged_config={
            "task_id": task_id,
            "tool_id": tool_id,
            "tool_version_id": tool_version_id,
        },
        agent_db_id="agent-1",
    )

    result = await executor(value="hello")

    assert result == "ok:hello"
    create_dto = create_mock.await_args.args[0]
    assert str(create_dto.task_id) == task_id
    assert create_dto.tool_id == tool_id
    assert create_dto.tool_version_id == tool_version_id
    assert create_dto.status == "running"
    assert create_dto.input == {"value": "hello"}

    update_dto = update_mock.await_args.args[0]
    assert update_dto.id == created_tool_call_id
    assert update_dto.status == "completed"
    assert update_dto.output == {"content": "ok:hello"}
    assert update_dto.error_message is None
    assert update_dto.duration_ms >= 0


@pytest.mark.asyncio
async def test_make_executor_persists_failed_tool_call(monkeypatch):
    task_id = str(uuid4())
    tool_id = uuid4()
    created_tool_call_id = uuid4()

    create_mock = AsyncMock(return_value=SimpleNamespace(id=created_tool_call_id))
    update_mock = AsyncMock()

    monkeypatch.setattr(
        tools_module,
        "ToolCallDAO",
        SimpleNamespace(create=create_mock, update=update_mock),
        raising=False,
    )

    executor = _make_executor(
        implementation_ref="tests.unit.simple_tool_module:failing_tool",
        merged_config={
            "task_id": task_id,
            "tool_id": tool_id,
        },
        agent_db_id="agent-1",
    )

    with pytest.raises(RuntimeError, match="boom:oops"):
        await executor(value="oops")

    update_dto = update_mock.await_args.args[0]
    assert update_dto.id == created_tool_call_id
    assert update_dto.status == "failed"
    assert update_dto.error_message == "boom:oops"
    assert update_dto.duration_ms >= 0


@pytest.mark.asyncio
async def test_make_executor_skips_persistence_without_task_id(monkeypatch):
    create_mock = AsyncMock()
    update_mock = AsyncMock()

    monkeypatch.setattr(
        tools_module,
        "ToolCallDAO",
        SimpleNamespace(create=create_mock, update=update_mock),
        raising=False,
    )

    executor = _make_executor(
        implementation_ref="tests.unit.simple_tool_module:successful_tool",
        merged_config={},
        agent_db_id="agent-1",
    )

    result = await executor(value="hello")

    assert result == "ok:hello"
    create_mock.assert_not_awaited()
    update_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_make_executor_continues_when_create_persistence_fails(monkeypatch):
    create_mock = AsyncMock(side_effect=RuntimeError("db create failed"))
    update_mock = AsyncMock()

    monkeypatch.setattr(
        tools_module,
        "ToolCallDAO",
        SimpleNamespace(create=create_mock, update=update_mock),
        raising=False,
    )

    executor = _make_executor(
        implementation_ref="tests.unit.simple_tool_module:successful_tool",
        merged_config={
            "task_id": str(uuid4()),
            "tool_id": uuid4(),
        },
        agent_db_id="agent-1",
    )

    result = await executor(value="hello")

    assert result == "ok:hello"
    create_mock.assert_awaited_once()
    update_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_make_executor_continues_when_update_persistence_fails(monkeypatch):
    create_mock = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    update_mock = AsyncMock(side_effect=RuntimeError("db update failed"))

    monkeypatch.setattr(
        tools_module,
        "ToolCallDAO",
        SimpleNamespace(create=create_mock, update=update_mock),
        raising=False,
    )

    executor = _make_executor(
        implementation_ref="tests.unit.simple_tool_module:successful_tool",
        merged_config={
            "task_id": str(uuid4()),
            "tool_id": uuid4(),
        },
        agent_db_id="agent-1",
    )

    result = await executor(value="hello")

    assert result == "ok:hello"
    create_mock.assert_awaited_once()
    update_mock.assert_awaited_once()
