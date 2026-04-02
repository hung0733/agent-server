from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import api.dashboard as dashboard_module
from api.dashboard import DashboardDataProvider


def _agent(*, agent_id, user_id, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=agent_id,
        user_id=user_id,
        name=name,
        agent_id=name.lower(),
        is_sub_agent=False,
        status="idle",
    )


def _task(*, queue_id, task_id, claimed_by, queued_at, status="running", result_json=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=queue_id,
        task_id=task_id,
        claimed_by=claimed_by,
        queued_at=queued_at,
        status=status,
        error_message=None,
        result_json=result_json,
    )


def _message(*, message_id, created_at, sender_agent_id=None, receiver_agent_id=None, content_json=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        created_at=created_at,
        sender_agent_id=sender_agent_id,
        receiver_agent_id=receiver_agent_id,
        content_json=content_json or {},
        message_type="response",
    )


def _usage(*, user_id, agent_id, session_id: str, model_name: str, total_tokens: int, input_tokens: int, output_tokens: int, cost: str, created_at) -> SimpleNamespace:
    from decimal import Decimal

    return SimpleNamespace(
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        model_name=model_name,
        total_tokens=total_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=Decimal(cost),
        created_at=created_at,
    )


def _endpoint(*, endpoint_id, user_id, name: str, base_url: str, model_name: str, is_active: bool = True, api_key_encrypted: str = "secret") -> SimpleNamespace:
    return SimpleNamespace(
        id=endpoint_id,
        user_id=user_id,
        name=name,
        base_url=base_url,
        model_name=model_name,
        is_active=is_active,
        api_key_encrypted=api_key_encrypted,
    )


def _group(*, group_id, user_id, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=group_id, user_id=user_id, name=name)


def _level_assignment(*, assignment_id, group_id, endpoint_id, difficulty_level: int, involves_secrets: bool, priority: int = 0, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=assignment_id,
        group_id=group_id,
        endpoint_id=endpoint_id,
        difficulty_level=difficulty_level,
        involves_secrets=involves_secrets,
        priority=priority,
        is_active=is_active,
    )


@pytest.mark.asyncio
async def test_get_tasks_merges_user_queue_and_messages_sorted_newest_first(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    agent_alpha = uuid4()
    agent_beta = uuid4()
    outsider = uuid4()
    now = datetime.now(UTC)

    user_agents = [
        _agent(agent_id=agent_alpha, user_id=user_id, name="Alpha"),
        _agent(agent_id=agent_beta, user_id=user_id, name="Beta"),
    ]
    task_rows = [
        _task(
            queue_id=uuid4(),
            task_id=uuid4(),
            claimed_by=agent_alpha,
            queued_at=now - timedelta(minutes=10),
            result_json={"group": "handoff", "origin": "scheduler", "relatedTaskId": "task-42"},
        ),
        _task(
            queue_id=uuid4(),
            task_id=uuid4(),
            claimed_by=outsider,
            queued_at=now - timedelta(minutes=1),
            result_json={"group": "ignore", "origin": "external"},
        ),
    ]
    message_rows = [
        _message(
            message_id=uuid4(),
            created_at=now - timedelta(minutes=2),
            sender_agent_id=agent_beta,
            receiver_agent_id=agent_alpha,
            content_json={"content": "Need approval for launch checklist before publish."},
        ),
        _message(
            message_id=uuid4(),
            created_at=now - timedelta(minutes=3),
            sender_agent_id=outsider,
            receiver_agent_id=None,
            content_json={"content": "Ignore outsider activity."},
        ),
    ]

    async def fake_get_agents(user_id_value, limit=100):
        assert user_id_value == user_id
        return user_agents

    async def fake_get_tasks(limit=100, offset=0, status=None, start_time=None, end_time=None):
        return task_rows

    async def fake_get_messages(limit=100, offset=0, message_type=None, session=None, start_time=None, end_time=None):
        return [(m, "session-1") for m in message_rows]

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all_with_time_range", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(
            get_all=fake_get_messages,
            get_all_with_session_id=fake_get_messages,
            get_all_with_session_id_and_time_range=fake_get_messages,
        ),
        raising=False,
    )

    payload = await provider.get_tasks(user_id=user_id)

    assert payload["source"] == "mixed"
    assert [item["type"] for item in payload["items"]] == ["message", "running"]
    assert [item["sourceAgent"] for item in payload["items"]] == ["Beta", "Alpha"]
    assert payload["items"][0]["messageSnippet"] == "Need approval for launch checklist before publish."
    assert payload["items"][0]["targetAgent"] == "Alpha"
    assert payload["items"][1]["group"] == "handoff"
    assert payload["items"][1]["origin"] == "scheduler"
    assert payload["items"][1]["relatedTaskId"] == "task-42"
    assert payload["items"][0]["timestamp"] > payload["items"][1]["timestamp"]


@pytest.mark.asyncio
async def test_get_tasks_returns_empty_items_without_user_scoped_activity(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    user_agent = uuid4()
    outsider = uuid4()
    now = datetime.now(UTC)

    async def fake_get_agents(user_id_value, limit=100):
        assert user_id_value == user_id
        return [_agent(agent_id=user_agent, user_id=user_id, name="Owner")]

    async def fake_get_tasks(limit=100, offset=0, status=None, start_time=None, end_time=None):
        return [_task(queue_id=uuid4(), task_id=uuid4(), claimed_by=outsider, queued_at=now)]

    async def fake_get_messages(limit=100, offset=0, message_type=None, session=None, start_time=None, end_time=None):
        return [(_message(message_id=uuid4(), created_at=now, sender_agent_id=outsider), "session-1")]

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all_with_time_range", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(
            get_all=fake_get_messages,
            get_all_with_session_id=fake_get_messages,
            get_all_with_session_id_and_time_range=fake_get_messages,
        ),
        raising=False,
    )

    payload = await provider.get_tasks(user_id=user_id)

    assert payload["items"] == []
    assert payload["source"] == "mixed"
    assert payload["hasMore"] is False
    assert payload["nextCursor"] is None


@pytest.mark.asyncio
async def test_get_memory_returns_structured_user_scoped_summary(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    agent_alpha = uuid4()
    agent_beta = uuid4()
    outsider = uuid4()
    now = datetime(2026, 3, 29, 12, 0, tzinfo=UTC)

    async def fake_get_agents(user_id_value, limit=100):
        assert user_id_value == user_id
        return [
            _agent(agent_id=agent_alpha, user_id=user_id, name="Alpha"),
            _agent(agent_id=agent_beta, user_id=user_id, name="Beta"),
        ]

    async def fake_get_tasks(limit=8, offset=0, status=None):
        assert offset == 0
        return [
            _task(
                queue_id=uuid4(),
                task_id=uuid4(),
                claimed_by=agent_alpha,
                queued_at=now - timedelta(minutes=20),
                status="completed",
            ),
            _task(
                queue_id=uuid4(),
                task_id=uuid4(),
                claimed_by=outsider,
                queued_at=now - timedelta(minutes=5),
                status="failed",
            ),
        ]

    async def fake_get_messages(limit=8, offset=0, message_type=None, session=None):
        return [
            _message(
                message_id=uuid4(),
                created_at=now - timedelta(minutes=3),
                sender_agent_id=agent_beta,
                receiver_agent_id=agent_alpha,
                content_json={"summary": "Shared launch notes with final blockers."},
            ),
            _message(
                message_id=uuid4(),
                created_at=now - timedelta(minutes=1),
                sender_agent_id=outsider,
                content_json={"content": "Should not appear."},
            ),
        ]

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(get_all=fake_get_messages),
        raising=False,
    )

    payload = await provider.get_memory(user_id=user_id)

    assert payload["source"] == "mixed"
    assert payload["stats"] == {"agents": 2, "tasks": 1, "messages": 1}
    assert payload["health"]["status"] == "healthy"
    assert payload["health"]["summary"] == "最近 2 項用戶活動可歸因。"
    assert payload["recentEntries"][0]["kind"] == "message"
    assert payload["recentEntries"][0]["agent"] == "Beta"
    assert payload["recentEntries"][0]["summary"] == "Shared launch notes with final blockers."
    assert payload["recentEntries"][1]["kind"] == "task"
    assert payload["recentEntries"][1]["agent"] == "Alpha"


@pytest.mark.asyncio
async def test_user_scoped_activity_is_found_beyond_initial_global_limit(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    user_agent = uuid4()
    outsider = uuid4()
    now = datetime(2026, 3, 29, 12, 0, tzinfo=UTC)

    async def fake_get_agents(user_id_value, limit=100):
        assert user_id_value == user_id
        return [
            _agent(agent_id=user_agent, user_id=user_id, name="Primary Agent"),
            _agent(agent_id=uuid4(), user_id=user_id, name="fallback"),
        ]

    task_rows = [
        _task(queue_id=uuid4(), task_id=uuid4(), claimed_by=outsider, queued_at=now - timedelta(minutes=index))
        for index in range(8)
    ] + [
        _task(
            queue_id=uuid4(),
            task_id=uuid4(),
            claimed_by=user_agent,
            queued_at=now - timedelta(minutes=20),
            result_json={"origin": "scheduler"},
        )
    ]
    message_rows = [
        _message(message_id=uuid4(), created_at=now - timedelta(minutes=index), sender_agent_id=outsider)
        for index in range(8)
    ] + [
        _message(
            message_id=uuid4(),
            created_at=now - timedelta(minutes=15),
            sender_agent_id=user_agent,
            content_json={"content": "User-owned activity should still be included."},
        )
    ]

    async def fake_get_tasks(limit=8, offset=0, status=None):
        return task_rows[offset : offset + limit]

    async def fake_get_messages(limit=8, offset=0, message_type=None, session=None):
        return message_rows[offset : offset + limit]

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(get_all=fake_get_messages),
        raising=False,
    )

    tasks_payload = await provider.get_tasks(user_id=user_id)
    memory_payload = await provider.get_memory(user_id=user_id)

    assert [item["sourceAgent"] for item in tasks_payload["items"]] == ["Primary Agent", "Primary Agent"]
    assert tasks_payload["items"][0]["type"] == "message"
    assert tasks_payload["items"][1]["origin"] == "scheduler"
    assert memory_payload["stats"] == {"agents": 2, "tasks": 1, "messages": 1}
    assert [entry["agent"] for entry in memory_payload["recentEntries"]] == ["Primary Agent", "Primary Agent"]


@pytest.mark.asyncio
async def test_get_usage_aggregates_real_token_usage_without_mock_fallback(monkeypatch) -> None:
    from decimal import Decimal

    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    now = datetime.now(UTC)

    async def fake_get_usage(user_id_value, limit=500, offset=0, session=None):
        assert user_id_value == user_id
        return [
            _usage(
                user_id=user_id,
                agent_id=uuid4(),
                session_id="session-1",
                model_name="qwen3.5-35b-a3b",
                total_tokens=72,
                input_tokens=17,
                output_tokens=55,
                cost="0",
                created_at=now,
            ),
            _usage(
                user_id=user_id,
                agent_id=uuid4(),
                session_id="session-2",
                model_name="qwen3.5-35b-a3b",
                total_tokens=28,
                input_tokens=20,
                output_tokens=8,
                cost="0",
                created_at=now,
            ),
            _usage(
                user_id=user_id,
                agent_id=uuid4(),
                session_id="session-3",
                model_name="llama-3.1-8b",
                total_tokens=50,
                input_tokens=40,
                output_tokens=10,
                cost="0.25",
                created_at=now,
            ),
        ]

    monkeypatch.setattr(dashboard_module.TokenUsageDAO, "get_by_user_id", fake_get_usage)

    payload = await provider.get_usage(user_id=user_id)

    assert payload["todayTokens"] == 150
    assert payload["todayCostUsd"] == str(Decimal("0.25"))
    assert payload["total"] == 150
    assert payload["items"][0]["label"] == "qwen3.5-35b-a3b"
    assert payload["items"][0]["value"] == 100
    assert payload["items"][0]["percentage"] == pytest.approx(66.67, rel=0, abs=0.01)
    assert payload["items"][1]["label"] == "llama-3.1-8b"
    assert payload["items"][1]["value"] == 50


@pytest.mark.asyncio
async def test_get_settings_returns_endpoint_inventory_and_mapping_slots(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    group_id = uuid4()
    endpoint_id = uuid4()

    async def fake_groups(user_id_value, session=None):
        assert user_id_value == user_id
        return [_group(group_id=group_id, user_id=user_id, name="Default Group")]

    async def fake_endpoints(user_id_value, session=None):
        assert user_id_value == user_id
        return [
            _endpoint(
                endpoint_id=endpoint_id,
                user_id=user_id,
                name="Local Qwen",
                base_url="http://localhost:8601/v1",
                model_name="qwen3.5-35b-a3b",
            )
        ]

    async def fake_levels(group_id_value, session=None):
        assert group_id_value == group_id
        return [
            _level_assignment(
                assignment_id=uuid4(),
                group_id=group_id,
                endpoint_id=endpoint_id,
                difficulty_level=1,
                involves_secrets=False,
                priority=10,
            )
        ]

    async def fake_endpoint_usage(endpoint_id_value, session=None):
        assert endpoint_id_value == endpoint_id
        return SimpleNamespace(total=2)

    monkeypatch.setattr(dashboard_module.LLMEndpointGroupDAO, "get_by_user_id", fake_groups)
    monkeypatch.setattr(dashboard_module.LLMEndpointDAO, "get_by_user_id", fake_endpoints)
    monkeypatch.setattr(dashboard_module.LLMLevelEndpointDAO, "get_by_group_id", fake_levels)
    monkeypatch.setattr(dashboard_module.LLMLevelEndpointDAO, "get_by_endpoint_id", AsyncMock(return_value=None), raising=False)

    payload = await provider.get_settings(user_id=user_id)

    assert payload["source"] == "mixed"
    assert payload["endpoints"][0]["name"] == "Local Qwen"
    assert payload["endpoints"][0]["apiKeyConfigured"] is True
    assert payload["groups"][0]["name"] == "Default Group"
    assert payload["groups"][0]["slots"][0]["difficultyLevel"] == 1
    assert payload["groups"][0]["slots"][0]["endpointId"] == str(endpoint_id)


@pytest.mark.asyncio
async def test_get_settings_returns_auth_keys_without_raw_key(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    key_id = uuid4()
    now = datetime(2026, 3, 29, 18, 0, tzinfo=UTC)

    async def fake_groups(user_id_value, session=None):
        assert user_id_value == user_id
        return []

    async def fake_endpoints(user_id_value, session=None):
        assert user_id_value == user_id
        return []

    async def fake_api_keys(user_id_value, session=None):
        assert user_id_value == user_id
        return [
            SimpleNamespace(
                id=key_id,
                user_id=user_id,
                key_hash="sha256:abc",
                name="Dashboard main",
                is_active=True,
                last_used_at=now,
                expires_at=None,
                created_at=now,
            )
        ]

    monkeypatch.setattr(dashboard_module.LLMEndpointGroupDAO, "get_by_user_id", fake_groups)
    monkeypatch.setattr(dashboard_module.LLMEndpointDAO, "get_by_user_id", fake_endpoints)
    monkeypatch.setattr(dashboard_module.APIKeyDAO, "get_by_user_id", fake_api_keys)

    payload = await provider.get_settings(user_id=user_id)

    assert payload["authKeys"][0] == {
        "id": str(key_id),
        "name": "Dashboard main",
        "isActive": True,
        "lastUsedAt": now.isoformat(),
        "expiresAt": None,
        "createdAt": now.isoformat(),
    }


@pytest.mark.asyncio
async def test_get_agent_tools_returns_effective_tool_state(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    agent_id = uuid4()
    other_agent_id = uuid4()
    tool_id = uuid4()
    disabled_tool_id = uuid4()

    agent_row = SimpleNamespace(
        id=agent_id,
        user_id=user_id,
        name="Main",
        agent_id="main",
        is_sub_agent=False,
        status="idle",
        agent_type_id=uuid4(),
    )
    other_agent_row = SimpleNamespace(
        id=other_agent_id,
        user_id=user_id,
        name="Pandas",
        agent_id="pandas",
        is_sub_agent=True,
        status="busy",
        agent_type_id=uuid4(),
    )

    async def fake_get_agents(user_id_value, limit=100):
        assert user_id_value == user_id
        return [agent_row, other_agent_row]

    async def fake_get_active_tools(session=None):
        return [
            SimpleNamespace(id=tool_id, name="web_search", description="Search the web", is_active=True),
            SimpleNamespace(id=disabled_tool_id, name="file_reader", description="Read files", is_active=True),
        ]

    async def fake_get_effective_tools(instance_id, session=None):
        assert instance_id in {agent_id, other_agent_id}
        return [tool_id] if instance_id == agent_id else [tool_id, disabled_tool_id]

    async def fake_get_overrides(instance_id, session=None):
        if instance_id == agent_id:
            return [SimpleNamespace(tool_id=tool_id, is_enabled=True), SimpleNamespace(tool_id=disabled_tool_id, is_enabled=False)]
        return []

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.ToolDAO, "get_active", fake_get_active_tools)
    monkeypatch.setattr(dashboard_module.AgentInstanceToolDAO, "get_effective_tools", fake_get_effective_tools)
    monkeypatch.setattr(dashboard_module.AgentInstanceToolDAO, "get_overrides_for_instance", fake_get_overrides)

    payload = await provider.get_agent_tools(user_id=user_id)

    assert payload["source"] == "mixed"
    assert [agent["name"] for agent in payload["agents"]] == ["Main", "Pandas"]
    assert [tool["name"] for tool in payload["availableTools"]] == ["web_search", "file_reader"]
    assert payload["agents"][0]["tools"][0]["isEnabled"] is True
    assert payload["agents"][0]["tools"][1]["isEnabled"] is False
    assert payload["agents"][0]["tools"][1]["source"] == "override"


@pytest.mark.asyncio
async def test_get_tasks_returns_has_more_and_next_cursor_for_infinite_scroll(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    user_agent = uuid4()
    now = datetime.now(UTC)

    user_agents = [_agent(agent_id=user_agent, user_id=user_id, name="Alpha")]
    
    recent_message = _message(
        message_id=uuid4(),
        created_at=now - timedelta(hours=1),
        sender_agent_id=user_agent,
        content_json={"content": "Recent message"},
    )
    
    older_message = _message(
        message_id=uuid4(),
        created_at=now - timedelta(hours=48),
        sender_agent_id=user_agent,
        content_json={"content": "Older message"},
    )

    async def fake_get_agents(user_id_value, limit=100):
        return user_agents

    async def fake_get_tasks(limit=100, offset=0, status=None, start_time=None, end_time=None):
        return []

    async def fake_get_messages(limit=100, offset=0, message_type=None, session=None, start_time=None, end_time=None):
        messages = [(recent_message, "session-1"), (older_message, "session-1")]
        if start_time and end_time:
            return [(m, sid) for m, sid in messages if start_time <= m.created_at < end_time]
        elif end_time:
            return [(m, sid) for m, sid in messages if m.created_at < end_time]
        elif start_time:
            return [(m, sid) for m, sid in messages if m.created_at >= start_time]
        return messages[:1]

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(
            get_all=fake_get_messages,
            get_all_with_session_id=fake_get_messages,
            get_all_with_session_id_and_time_range=fake_get_messages,
        ),
        raising=False,
    )

    payload = await provider.get_tasks(user_id=user_id)

    assert "hasMore" in payload
    assert "nextCursor" in payload
    assert payload["hasMore"] is True
    assert payload["nextCursor"] is not None
    assert len(payload["items"]) >= 1


@pytest.mark.asyncio
async def test_get_tasks_with_before_parameter_returns_previous_24_hours(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    user_agent = uuid4()
    now = datetime.now(UTC)
    before_time = now - timedelta(hours=24)

    user_agents = [_agent(agent_id=user_agent, user_id=user_id, name="Alpha")]
    
    older_message = _message(
        message_id=uuid4(),
        created_at=now - timedelta(hours=48),
        sender_agent_id=user_agent,
        content_json={"content": "Older message"},
    )
    
    very_old_message = _message(
        message_id=uuid4(),
        created_at=now - timedelta(hours=72),
        sender_agent_id=user_agent,
        content_json={"content": "Very old message"},
    )

    async def fake_get_agents(user_id_value, limit=100):
        return user_agents

    async def fake_get_tasks(limit=100, offset=0, status=None, start_time=None, end_time=None):
        return []

    async def fake_get_messages(limit=100, offset=0, message_type=None, session=None, start_time=None, end_time=None):
        messages = [(older_message, "session-1"), (very_old_message, "session-1")]
        if start_time and end_time:
            return [(m, sid) for m, sid in messages if start_time <= m.created_at < end_time]
        return messages

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all_with_time_range", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(
            get_all=fake_get_messages,
            get_all_with_session_id=fake_get_messages,
            get_all_with_session_id_and_time_range=fake_get_messages,
        ),
        raising=False,
    )

    payload = await provider.get_tasks(user_id=user_id, before=before_time)

    assert len(payload["items"]) >= 1
    older_items = [item for item in payload["items"] if "Older" in item.get("summary", "") or "Very old" in item.get("summary", "")]
    assert len(older_items) >= 1
