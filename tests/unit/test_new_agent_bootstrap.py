from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.new_agent_bootstrap import _resolve_active_endpoints, extract_soul_draft


@pytest.mark.asyncio
async def test_resolve_active_endpoints_uses_default_group_enriched_rows(monkeypatch) -> None:
    agent = SimpleNamespace(id="agent-db-id")
    default_group = SimpleNamespace(id="group-1")
    endpoint = SimpleNamespace(is_active=True, model_name="gpt-4o-mini")

    monkeypatch.setattr(
        "api.new_agent_bootstrap.LLMLevelEndpointDAO.get_by_agent_instance_id",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "api.new_agent_bootstrap.LLMEndpointGroupDAO.get_default_group",
        AsyncMock(return_value=default_group),
    )
    enriched_mock = AsyncMock(return_value=[endpoint])
    monkeypatch.setattr(
        "api.new_agent_bootstrap.LLMLevelEndpointDAO.get_endpoints_with_level_by_group_id",
        enriched_mock,
    )

    result = await _resolve_active_endpoints(agent, "user-1")

    assert result == [endpoint]
    assert enriched_mock.await_args.args == (default_group.id,)


def test_extract_soul_draft_prefers_tagged_output() -> None:
    reply = """收到，以下係草稿。

<SOUL_DRAFT>
# SOUL
Use English by default.
</SOUL_DRAFT>

已切換到 Build Mode.
"""

    assert extract_soul_draft(reply) == "# SOUL\nUse English by default."


def test_extract_soul_draft_rejects_untagged_chatty_output() -> None:
    reply = "收到，**SOUL.md** 已即時保存並鎖定。請問第一件事要點處理？"

    assert extract_soul_draft(reply) is None
