from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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


@pytest.mark.asyncio
async def test_get_tasks_merges_user_queue_and_messages_sorted_newest_first(monkeypatch) -> None:
    provider = DashboardDataProvider(queue=object(), dedup=object())
    user_id = uuid4()
    agent_alpha = uuid4()
    agent_beta = uuid4()
    outsider = uuid4()
    now = datetime(2026, 3, 29, 12, 0, tzinfo=UTC)

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

    async def fake_get_tasks(limit=8, status=None):
        assert limit == 8
        return task_rows

    async def fake_get_messages(limit=8, offset=0, message_type=None, session=None):
        assert limit == 8
        return message_rows

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(get_all=fake_get_messages),
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
    now = datetime(2026, 3, 29, 12, 0, tzinfo=UTC)

    async def fake_get_agents(user_id_value, limit=100):
        assert user_id_value == user_id
        return [_agent(agent_id=user_agent, user_id=user_id, name="Owner")]

    async def fake_get_tasks(limit=8, status=None):
        return [_task(queue_id=uuid4(), task_id=uuid4(), claimed_by=outsider, queued_at=now)]

    async def fake_get_messages(limit=8, offset=0, message_type=None, session=None):
        return [_message(message_id=uuid4(), created_at=now, sender_agent_id=outsider)]

    monkeypatch.setattr(dashboard_module.AgentInstanceDAO, "get_by_user_id", fake_get_agents)
    monkeypatch.setattr(dashboard_module.TaskQueueDAO, "get_all", fake_get_tasks)
    monkeypatch.setattr(
        dashboard_module,
        "AgentMessageDAO",
        SimpleNamespace(get_all=fake_get_messages),
        raising=False,
    )

    payload = await provider.get_tasks(user_id=user_id)

    assert payload == {"items": [], "source": "mixed"}


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

    async def fake_get_tasks(limit=8, status=None):
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
