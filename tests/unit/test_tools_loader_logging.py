from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tools.tools import get_tools


@pytest.mark.asyncio
async def test_get_tools_logs_loaded_tools_at_debug(monkeypatch):
    agent_db_id = str(uuid4())
    tool_id = uuid4()

    monkeypatch.setattr(
        "tools.tools.AgentInstanceDAO.get_by_id",
        AsyncMock(return_value=SimpleNamespace(user_id=uuid4())),
    )
    monkeypatch.setattr(
        "tools.tools.AgentInstanceToolDAO.get_effective_tools",
        AsyncMock(return_value=[tool_id]),
    )
    monkeypatch.setattr(
        "tools.tools.AgentInstanceToolDAO.get_overrides_for_instance",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "tools.tools.ToolDAO.get_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                name="ls",
                description="列出目錄內容。",
                is_active=True,
            )
        ),
    )
    monkeypatch.setattr(
        "tools.tools.ToolVersionDAO.get_default_version",
        AsyncMock(
            return_value=SimpleNamespace(
                version="1.0.0",
                implementation_ref="tools.system_tools:ls_impl",
                config_json={},
                input_schema={"type": "object", "properties": {}},
            )
        ),
    )

    debug_messages = []
    info_messages = []

    monkeypatch.setattr("tools.tools.logger.debug", lambda message, *args: debug_messages.append(message % args))
    monkeypatch.setattr("tools.tools.logger.info", lambda message, *args: info_messages.append(message % args))

    tools = await get_tools(agent_db_id)

    assert len(tools) == 1
    assert any("已載入工具" in message for message in debug_messages)
    assert any("共載入" in message for message in info_messages)
    assert any("可用工具列表" in message for message in info_messages)
