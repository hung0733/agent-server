from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from datetime import timedelta
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer



def _parse_duration_stub(value: str):
    if value == "PT2H":
        return timedelta(hours=2)
    if value == "PT1H":
        return timedelta(hours=1)
    raise ValueError(value)


sys.modules.setdefault("isodate", types.SimpleNamespace(parse_duration=_parse_duration_stub))

import api.app as app_module
from api.app import create_app


class _FakeQueue:
    def qsize(self) -> int:
        return 3


class _FakeDedup:
    size = 7


class _FakeDashboardProvider:
    def __init__(self) -> None:
        self.last_user_id = None

    async def get_overview(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {"summary": {"headline": "ok"}, "source": "mixed"}

    async def get_usage(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {"total": 42, "items": [], "source": "mixed"}

    async def get_agents(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {"agents": [{"id": "main"}], "source": "mixed"}

    async def get_tasks(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {"items": [{"id": "evt-1"}], "source": "mixed"}

    async def get_memory(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {
            "stats": {"agents": 1, "tasks": 2, "messages": 3},
            "health": {"status": "healthy", "summary": "最近 5 項用戶活動可歸因。"},
            "recentEntries": [
                {
                    "kind": "message",
                    "agent": "main",
                    "summary": "ok",
                    "status": "healthy",
                    "timestamp": "2026-03-29T12:00:00+00:00",
                }
            ],
            "source": "mixed",
        }

    async def get_settings(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {"locales": ["zh-HK"], "featureFlags": {}, "endpoints": [], "groups": [], "authKeys": [], "source": "mixed"}

    async def get_agent_tools(self, user_id=None) -> dict:
        self.last_user_id = user_id
        return {"agents": [], "availableTools": [], "source": "mixed"}


class _FakeAuthService:
    def __init__(self, user_id):
        self.user_id = user_id

    async def authenticate(self, raw_key: str):
        if raw_key == "good-key":
            return {"user_id": self.user_id}
        return None


class _FakeJanitorTask:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None

        return _done().__await__()


@pytest.mark.asyncio
async def test_create_app_starts_and_stops_sandbox_janitor(monkeypatch) -> None:
    janitor_task = _FakeJanitorTask()
    create_task = MagicMock(side_effect=lambda coro: (coro.close(), janitor_task)[1])
    cleanup_calls = []
    monkeypatch.setenv("SANDBOX_BACKEND", "local_docker")
    monkeypatch.setenv("SANDBOX_IDLE_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("SANDBOX_AGENT_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("AGENT_HOME_DIR", "/tmp/agent-home")
    monkeypatch.setenv("SANDBOX_API_TOKEN", "secret")
    monkeypatch.setattr(app_module.asyncio, "create_task", create_task)
    monkeypatch.setattr(
        app_module,
        "run_sandbox_janitor_once",
        AsyncMock(side_effect=lambda provider, idle_timeout: cleanup_calls.append((provider, idle_timeout))),
    )

    app = create_app(_FakeQueue(), _FakeDedup(), dashboard_data_provider=_FakeDashboardProvider())
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    await client.close()

    assert create_task.called
    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][1] == 1800
    assert janitor_task.cancelled is True


@pytest.mark.asyncio
async def test_create_app_ignores_startup_cleanup_failures(monkeypatch) -> None:
    janitor_task = _FakeJanitorTask()
    monkeypatch.setenv("SANDBOX_BACKEND", "local_docker")
    monkeypatch.setenv("SANDBOX_IDLE_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("SANDBOX_AGENT_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("AGENT_HOME_DIR", "/tmp/agent-home")
    monkeypatch.setenv("SANDBOX_API_TOKEN", "secret")
    monkeypatch.setattr(app_module.asyncio, "create_task", MagicMock(side_effect=lambda coro: (coro.close(), janitor_task)[1]))
    monkeypatch.setattr(app_module, "run_sandbox_janitor_once", AsyncMock(side_effect=RuntimeError("boom")))

    app = create_app(_FakeQueue(), _FakeDedup(), dashboard_data_provider=_FakeDashboardProvider())
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    await client.close()


class _FakeSchedule:
    def __init__(self, schedule_id, task_template_id, schedule_type="cron", schedule_expression="0 12 * * *", is_active=True, next_run_at=None, last_run_at=None):
        self.id = schedule_id
        self.task_template_id = task_template_id
        self.schedule_type = schedule_type
        self.schedule_expression = schedule_expression
        self.is_active = is_active
        self.next_run_at = next_run_at
        self.last_run_at = last_run_at


class _FakeTask:
    def __init__(self, task_id, user_id, agent_id, task_type, payload):
        self.id = task_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.task_type = task_type
        self.payload = payload


@pytest.mark.asyncio
async def test_health_returns_queue_and_dedup_stats(tmp_path: Path) -> None:
    app = create_app(_FakeQueue(), _FakeDedup(), dashboard_data_provider=_FakeDashboardProvider())
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get("/health")
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload == {"status": "ok", "queue_size": 3, "dedup_tracked": 7}


@pytest.mark.asyncio
async def test_dashboard_endpoints_return_provider_payloads() -> None:
    provider = _FakeDashboardProvider()
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=provider,
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get("/api/dashboard/overview", headers={"X-API-Key": "good-key"})
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["summary"]["headline"] == "ok"
    assert payload["source"] == "mixed"
    assert provider.last_user_id == user_id


@pytest.mark.asyncio
async def test_memory_endpoint_returns_provider_contract_shape() -> None:
    provider = _FakeDashboardProvider()
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=provider,
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get("/api/dashboard/memory", headers={"X-API-Key": "good-key"})
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["stats"] == {"agents": 1, "tasks": 2, "messages": 3}
    assert payload["health"]["summary"] == "最近 5 項用戶活動可歸因。"
    assert payload["recentEntries"][0]["kind"] == "message"
    assert payload["source"] == "mixed"


@pytest.mark.asyncio
async def test_schedule_endpoint_returns_method_and_message_groups(monkeypatch) -> None:
    user_id = uuid4()
    method_task_id = uuid4()
    message_task_id = uuid4()
    method_schedule_id = uuid4()
    message_schedule_id = uuid4()
    agent_id = uuid4()
    next_run = datetime(2026, 4, 4, 8, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 4, 4, 1, 30, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        app_module.TaskScheduleDAO,
        "get_all",
        AsyncMock(
            return_value=[
                _FakeSchedule(method_schedule_id, method_task_id),
                _FakeSchedule(
                    message_schedule_id,
                    message_task_id,
                    schedule_type="interval",
                    schedule_expression="PT2H",
                    next_run_at=next_run,
                    last_run_at=last_run,
                ),
            ]
        ),
    )
    monkeypatch.setattr(
        app_module.TaskDAO,
        "get_by_id",
        AsyncMock(
            side_effect=[
                _FakeTask(
                    method_task_id,
                    user_id,
                    agent_id,
                    "scheduled_method",
                    {"task_execution_type": "method", "name": "Daily review", "prompt": "", "method_path": "agent.bulter@Bulter.review_ltm"},
                ),
                _FakeTask(
                    message_task_id,
                    user_id,
                    agent_id,
                    "scheduled_message",
                    {"task_execution_type": "message", "name": "Morning ping", "prompt": "send summary"},
                ),
            ]
        ),
    )
    monkeypatch.setattr(
        app_module.AgentInstanceDAO,
        "get_by_id",
        AsyncMock(return_value=type("Agent", (), {"id": agent_id, "name": "otter", "agent_id": "agent-otter"})()),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get("/api/dashboard/schedules", headers={"X-API-Key": "good-key"})
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["methodSchedules"][0]["taskType"] == "method"
    assert payload["messageSchedules"][0]["taskType"] == "message"
    assert payload["messageSchedules"][0]["name"] == "Morning ping"
    assert payload["messageSchedules"][0]["nextRunAt"].endswith("+08:00")
    assert payload["messageSchedules"][0]["lastRunAt"].endswith("+08:00")


@pytest.mark.asyncio
async def test_method_schedule_rejects_write_actions(monkeypatch) -> None:
    user_id = uuid4()
    task_id = uuid4()
    schedule_id = uuid4()
    agent_id = uuid4()

    monkeypatch.setattr(
        app_module.TaskScheduleDAO,
        "get_by_id",
        AsyncMock(return_value=_FakeSchedule(schedule_id, task_id)),
    )
    monkeypatch.setattr(
        app_module.TaskDAO,
        "get_by_id",
        AsyncMock(
            return_value=_FakeTask(
                task_id,
                user_id,
                agent_id,
                "scheduled_method",
                {"task_execution_type": "method", "name": "Daily review", "method_path": "agent.bulter@Bulter.review_ltm"},
            )
        ),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.patch(
            f"/api/dashboard/schedules/message/{schedule_id}",
            headers={"X-API-Key": "good-key"},
            json={"name": "changed", "prompt": "changed", "scheduleType": "cron", "scheduleExpression": "0 8 * * *", "isActive": True},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 400
    assert payload["error"] == "schedule_not_editable"


@pytest.mark.asyncio
async def test_create_message_schedule_returns_serialized_schedule(monkeypatch) -> None:
    user_id = uuid4()
    agent_id = uuid4()
    task_id = uuid4()
    schedule_id = uuid4()

    monkeypatch.setattr(
        app_module.AgentInstanceDAO,
        "get_by_id",
        AsyncMock(return_value=type("Agent", (), {"id": agent_id, "name": "main", "agent_id": "agent-main", "user_id": user_id})()),
    )
    monkeypatch.setattr(
        app_module.TaskDAO,
        "create",
        AsyncMock(
            return_value=_FakeTask(
                task_id,
                user_id,
                agent_id,
                "message",
                {"task_execution_type": "message", "name": "Morning ping", "prompt": "send summary"},
            )
        ),
    )
    monkeypatch.setattr(
        app_module.TaskScheduleDAO,
        "create",
        AsyncMock(return_value=_FakeSchedule(schedule_id, task_id, schedule_type="interval", schedule_expression="PT2H")),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            "/api/dashboard/schedules/message",
            headers={"X-API-Key": "good-key"},
            json={
                "agentId": str(agent_id),
                "name": "Morning ping",
                "prompt": "send summary",
                "scheduleType": "interval",
                "scheduleExpression": "PT2H",
                "isActive": True,
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 201
    assert payload["schedule"]["taskType"] == "message"
    assert payload["schedule"]["name"] == "Morning ping"
    assert payload["schedule"]["agentName"] == "main"


@pytest.mark.asyncio
async def test_refresh_message_schedule_updates_next_run(monkeypatch) -> None:
    user_id = uuid4()
    task_id = uuid4()
    schedule_id = uuid4()
    agent_id = uuid4()

    monkeypatch.setattr(
        app_module.TaskScheduleDAO,
        "get_by_id",
        AsyncMock(return_value=_FakeSchedule(schedule_id, task_id, schedule_type="interval", schedule_expression="PT2H")),
    )
    monkeypatch.setattr(
        app_module.TaskDAO,
        "get_by_id",
        AsyncMock(
            return_value=_FakeTask(
                task_id,
                user_id,
                agent_id,
                "message",
                {"task_execution_type": "message", "name": "Morning ping", "prompt": "send summary"},
            )
        ),
    )
    monkeypatch.setattr(
        app_module.AgentInstanceDAO,
        "get_by_id",
        AsyncMock(return_value=type("Agent", (), {"id": agent_id, "name": "main", "agent_id": "agent-main"})()),
    )
    monkeypatch.setattr(
        app_module.TaskScheduleDAO,
        "update",
        AsyncMock(return_value=_FakeSchedule(schedule_id, task_id, schedule_type="interval", schedule_expression="PT2H")),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            f"/api/dashboard/schedules/message/{schedule_id}/refresh",
            headers={"X-API-Key": "good-key"},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["schedule"]["id"] == str(schedule_id)
    assert payload["schedule"]["taskType"] == "message"


@pytest.mark.asyncio
async def test_dashboard_endpoints_require_api_key() -> None:
    app = create_app(_FakeQueue(), _FakeDedup(), dashboard_data_provider=_FakeDashboardProvider())
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get("/api/dashboard/agents")
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 401
    assert payload["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_spa_routes_serve_built_frontend(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>spa shell</body></html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        frontend_dist=dist,
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        route_response = await client.get("/usage")
        asset_response = await client.get("/assets/app.js")
        route_text = await route_response.text()
        asset_text = await asset_response.text()
    finally:
        await client.close()

    assert route_response.status == 200
    assert "spa shell" in route_text
    assert asset_response.status == 200
    assert "console.log" in asset_text


@pytest.mark.asyncio
async def test_endpoint_crud_routes_require_valid_auth_and_return_json(monkeypatch) -> None:
    user_id = uuid4()
    endpoint_id = uuid4()

    monkeypatch.setattr(
        "api.app.CryptoManager",
        lambda: type("FakeCrypto", (), {"encrypt": staticmethod(lambda value: f"enc:{value}")})(),
    )
    monkeypatch.setattr(
        "api.app.LLMEndpointDAO.create",
        AsyncMock(
            return_value=type(
                "Endpoint",
                (),
                {
                    "id": endpoint_id,
                    "name": "Local Qwen",
                    "base_url": "http://localhost:8601/v1",
                    "model_name": "qwen",
                    "is_active": True,
                },
            )()
        ),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            "/api/dashboard/settings/endpoints",
            headers={"X-API-Key": "good-key"},
            json={
                "name": "Local Qwen",
                "baseUrl": "http://localhost:8601/v1",
                "modelName": "qwen",
                "apiKey": "EMPTY",
                "isActive": True,
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["endpoint"]["id"] == str(endpoint_id)
    assert payload["endpoint"]["name"] == "Local Qwen"


@pytest.mark.asyncio
async def test_delete_endpoint_rejects_when_mapping_exists(monkeypatch) -> None:
    user_id = uuid4()
    endpoint_id = uuid4()

    monkeypatch.setattr(
        "api.app.LLMEndpointDAO.get_by_id",
        AsyncMock(return_value=type("Endpoint", (), {"id": endpoint_id, "user_id": user_id})()),
    )
    monkeypatch.setattr(
        "api.app.LLMLevelEndpointDAO.get_by_endpoint_id",
        AsyncMock(return_value=type("LevelAssignment", (), {"id": uuid4()})()),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.delete(
            f"/api/dashboard/settings/endpoints/{endpoint_id}",
            headers={"X-API-Key": "good-key"},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 409
    assert payload["error"] == "endpoint_in_use"


@pytest.mark.asyncio
async def test_auth_key_routes_create_and_regenerate_one_time_secret(monkeypatch) -> None:
    user_id = uuid4()
    key_id = uuid4()
    regenerated_id = uuid4()

    monkeypatch.setattr(
        app_module.APIKeyDAO,
        "create",
        AsyncMock(
            side_effect=[
                type("Key", (), {"id": key_id, "user_id": user_id, "name": "Main key", "is_active": True, "last_used_at": None, "expires_at": None, "created_at": None})(),
                type("Key", (), {"id": regenerated_id, "user_id": user_id, "name": "Main key", "is_active": True, "last_used_at": None, "expires_at": None, "created_at": None})(),
            ]
        ),
    )
    monkeypatch.setattr(
        app_module.APIKeyDAO,
        "get_by_id",
        AsyncMock(return_value=type("Key", (), {"id": key_id, "user_id": user_id, "name": "Main key", "is_active": True, "last_used_at": None, "expires_at": None, "created_at": None})()),
    )
    monkeypatch.setattr(app_module.APIKeyDAO, "update", AsyncMock())

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        create_response = await client.post(
            "/api/dashboard/settings/auth-keys",
            headers={"X-API-Key": "good-key"},
            json={"name": "Main key"},
        )
        create_payload = await create_response.json()

        regenerate_response = await client.post(
            f"/api/dashboard/settings/auth-keys/{key_id}/regenerate",
            headers={"X-API-Key": "good-key"},
            json={"name": "Main key"},
        )
        regenerate_payload = await regenerate_response.json()
    finally:
        await client.close()

    assert create_response.status == 200
    assert create_payload["key"]["id"] == str(key_id)
    assert create_payload["rawKey"]
    assert regenerate_response.status == 200
    assert regenerate_payload["key"]["id"] == str(regenerated_id)
    assert regenerate_payload["rawKey"]


@pytest.mark.asyncio
async def test_auth_key_delete_and_toggle_routes_are_user_scoped(monkeypatch) -> None:
    user_id = uuid4()
    key_id = uuid4()
    monkeypatch.setattr(
        app_module.APIKeyDAO,
        "get_by_id",
        AsyncMock(return_value=type("Key", (), {"id": key_id, "user_id": user_id, "name": "Main key", "is_active": True, "last_used_at": None, "expires_at": None, "created_at": None})()),
    )
    monkeypatch.setattr(
        app_module.APIKeyDAO,
        "update",
        AsyncMock(return_value=type("Key", (), {"id": key_id, "user_id": user_id, "name": "Main key", "is_active": False, "last_used_at": None, "expires_at": None, "created_at": None})()),
    )
    monkeypatch.setattr(app_module.APIKeyDAO, "delete", AsyncMock(return_value=True))

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        patch_response = await client.patch(
            f"/api/dashboard/settings/auth-keys/{key_id}",
            headers={"X-API-Key": "good-key"},
            json={"isActive": False},
        )
        patch_payload = await patch_response.json()
        delete_response = await client.delete(
            f"/api/dashboard/settings/auth-keys/{key_id}",
            headers={"X-API-Key": "good-key"},
        )
        delete_payload = await delete_response.json()
    finally:
        await client.close()

    assert patch_response.status == 200
    assert patch_payload["key"]["isActive"] is False
    assert delete_response.status == 200
    assert delete_payload == {"deleted": True}


@pytest.mark.asyncio
async def test_agent_tools_routes_return_provider_payloads_and_update_overrides(monkeypatch) -> None:
    user_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()
    override_id = uuid4()

    monkeypatch.setattr(
        app_module.AgentInstanceDAO,
        "get_by_id",
        AsyncMock(return_value=type("Agent", (), {"id": agent_id, "user_id": user_id})()),
    )
    monkeypatch.setattr(
        app_module.AgentInstanceToolDAO,
        "get_overrides_for_instance",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        app_module.AgentInstanceToolDAO,
        "assign",
        AsyncMock(return_value=type("Override", (), {"id": override_id, "agent_instance_id": agent_id, "tool_id": tool_id, "is_enabled": True, "config_override": None})()),
    )
    monkeypatch.setattr(
        app_module.ToolDAO,
        "get_by_id",
        AsyncMock(return_value=type("Tool", (), {"id": tool_id, "name": "web_search", "description": "Search", "is_active": True})()),
    )

    provider = _FakeDashboardProvider()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=provider,
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        get_response = await client.get("/api/dashboard/agents/tools", headers={"X-API-Key": "good-key"})
        get_payload = await get_response.json()

        patch_response = await client.patch(
            f"/api/dashboard/agents/{agent_id}/tools/{tool_id}",
            headers={"X-API-Key": "good-key"},
            json={"isEnabled": True},
        )
        patch_payload = await patch_response.json()
    finally:
        await client.close()

    assert get_response.status == 200
    assert get_payload["source"] == "mixed"
    assert patch_response.status == 200
    assert patch_payload["tool"]["id"] == str(override_id)


@pytest.mark.asyncio
async def test_agent_types_list_returns_empty_for_user() -> None:
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_all = AsyncMock(return_value=[])
        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/api/dashboard/agent-types", headers={"X-API-Key": "good-key"}
            )
            payload = await response.json()

    assert response.status == 200
    assert payload == {"agentTypes": []}
    mock_dao.get_all.assert_awaited_once_with(user_id=user_id)


@pytest.mark.asyncio
async def test_agent_types_create_returns_201() -> None:
    from datetime import datetime, timezone
    user_id = uuid4()
    type_id = uuid4()
    now = datetime.now(timezone.utc)

    fake = type(
        "_FakeAgentType",
        (),
        {"id": type_id, "name": "TestType", "description": "desc", "is_active": True, "created_at": now, "user_id": user_id},
    )()

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.create = AsyncMock(return_value=fake)
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/api/dashboard/agent-types",
                headers={"X-API-Key": "good-key"},
                json={"name": "TestType", "description": "desc"},
            )
            payload = await response.json()

    assert response.status == 201
    assert payload["agentType"]["name"] == "TestType"
    assert payload["agentType"]["description"] == "desc"
    assert payload["agentType"]["isActive"] is True


@pytest.mark.asyncio
async def test_agent_types_create_returns_409_on_duplicate_name() -> None:
    from sqlalchemy.exc import IntegrityError
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.create = AsyncMock(side_effect=IntegrityError("unique", {}, Exception()))
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/api/dashboard/agent-types",
                headers={"X-API-Key": "good-key"},
                json={"name": "Duplicate"},
            )
            payload = await response.json()

    assert response.status == 409
    assert payload["error"] == "name_already_exists"


@pytest.mark.asyncio
async def test_agent_types_update_returns_updated() -> None:
    from datetime import datetime, timezone
    user_id = uuid4()
    type_id = uuid4()
    now = datetime.now(timezone.utc)

    fake = type(
        "_FakeAgentType",
        (),
        {"id": type_id, "name": "Updated", "description": None, "is_active": False, "created_at": now, "user_id": user_id},
    )()

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_by_id = AsyncMock(return_value=fake)
        mock_dao.update = AsyncMock(return_value=fake)
        async with TestClient(TestServer(app)) as client:
            response = await client.patch(
                f"/api/dashboard/agent-types/{type_id}",
                headers={"X-API-Key": "good-key"},
                json={"name": "Updated", "isActive": False},
            )
            payload = await response.json()

    assert response.status == 200
    assert payload["agentType"]["name"] == "Updated"
    assert payload["agentType"]["isActive"] is False


@pytest.mark.asyncio
async def test_agent_types_update_returns_404_for_wrong_user() -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    type_id = uuid4()

    fake = type("_FakeAgentType", (), {"id": type_id, "user_id": other_user_id})()

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_by_id = AsyncMock(return_value=fake)
        async with TestClient(TestServer(app)) as client:
            response = await client.patch(
                f"/api/dashboard/agent-types/{type_id}",
                headers={"X-API-Key": "good-key"},
                json={"name": "Hacked"},
            )

    assert response.status == 404


@pytest.mark.asyncio
async def test_agent_types_delete_returns_deleted_true() -> None:
    user_id = uuid4()
    type_id = uuid4()

    fake = type("_FakeAgentType", (), {"id": type_id, "user_id": user_id})()

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_by_id = AsyncMock(return_value=fake)
        mock_dao.delete = AsyncMock(return_value=True)
        async with TestClient(TestServer(app)) as client:
            response = await client.delete(
                f"/api/dashboard/agent-types/{type_id}",
                headers={"X-API-Key": "good-key"},
            )
            payload = await response.json()

    assert response.status == 200
    assert payload == {"deleted": True}


@pytest.mark.asyncio
async def test_agent_types_require_auth() -> None:
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
    )
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/dashboard/agent-types")

    assert response.status == 401


@pytest.mark.asyncio
async def test_agents_create_accepts_endpoint_group_and_memory_blocks(monkeypatch) -> None:
    user_id = uuid4()
    agent_type_id = uuid4()
    agent_id_val = uuid4()
    endpoint_group_id = uuid4()

    fake_type = type("AgentType", (), {"id": agent_type_id, "user_id": user_id, "name": "Test Type"})()
    fake_agent = type(
        "Agent",
        (),
        {
            "id": agent_id_val,
            "user_id": user_id,
            "name": "Butler",
            "agent_type_id": agent_type_id,
            "status": "idle",
            "phone_no": None,
            "whatsapp_key": None,
            "is_sub_agent": False,
            "is_active": True,
            "agent_id": f"agent-{agent_id_val}",
            "endpoint_group_id": endpoint_group_id,
            "created_at": None,
        },
    )()
    fake_session = type("Session", (), {"id": uuid4()})()
    fake_block = type("Block", (), {"id": uuid4()})()
    fake_task = type("Task", (), {"id": uuid4()})()
    fake_schedule = type("Schedule", (), {"id": uuid4()})()

    # Mock the transaction machinery so no real DB engine is created
    fake_db_session = MagicMock()
    fake_db_session.__aenter__ = AsyncMock(return_value=fake_db_session)
    fake_db_session.__aexit__ = AsyncMock(return_value=False)
    fake_db_session.begin = MagicMock(return_value=fake_db_session)
    fake_session_factory = MagicMock(return_value=fake_db_session)
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr("api.app.create_engine", MagicMock(return_value=fake_engine))
    monkeypatch.setattr("api.app.async_sessionmaker", MagicMock(return_value=fake_session_factory))

    monkeypatch.setattr("api.app.AgentTypeDAO.get_by_id", AsyncMock(return_value=fake_type))
    monkeypatch.setattr("api.app.AgentInstanceDAO.create", AsyncMock(return_value=fake_agent))
    monkeypatch.setattr(
        "api.app.CollaborationSessionDAO.create", AsyncMock(return_value=fake_session)
    )
    monkeypatch.setattr("api.app.MemoryBlockDAO.create", AsyncMock(return_value=fake_block))
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id", AsyncMock(return_value=[])
    )
    monkeypatch.setattr("api.app.TaskDAO.create", AsyncMock(return_value=fake_task))
    monkeypatch.setattr("api.app.TaskScheduleDAO.create", AsyncMock(return_value=fake_schedule))

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            "/api/dashboard/agents",
            headers={"X-API-Key": "good-key"},
            json={
                "name": "Butler",
                "agentTypeId": str(agent_type_id),
                "endpointGroupId": str(endpoint_group_id),
                "memoryBlocks": {"SOUL": "你是一個友善的助手", "USER_PROFILE": "", "IDENTITY": ""},
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 201
    assert payload["agent"]["endpointGroupId"] == str(endpoint_group_id)
    # Only SOUL was non-empty — MemoryBlockDAO.create called once
    from api.app import MemoryBlockDAO
    assert MemoryBlockDAO.create.call_count == 1
    created_block = MemoryBlockDAO.create.await_args.args[0]
    assert created_block.memory_type == "SOUL"
    assert created_block.content == "你是一個友善的助手"
    from api.app import TaskDAO
    assert TaskDAO.create.await_count == 2
    for call in TaskDAO.create.await_args_list:
        task_dto = call.args[0]
        assert task_dto.agent_id == agent_id_val
        assert task_dto.payload["agent_instance_id"] == str(agent_id_val)


@pytest.mark.asyncio
async def test_agents_bootstrap_returns_selected_mode_prompt(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()

    fake_agent = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "agent_id": f"agent-{agent_instance_id}",
            "name": "Butler",
        },
    )()

    soul_block = type(
        "Block",
        (),
        {
            "memory_type": "SOUL",
            "content": "Existing soul\n\n<system-reminder>\nYour operational mode has changed from plan to build.\nYou are no longer in read-only mode.\nYou are permitted to make file changes, run shell commands, and utilize your arsenal of tools as needed.\n</system-reminder>"
        },
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id", AsyncMock(return_value=[soul_block])
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            f"/api/dashboard/agents/{agent_instance_id}/bootstrap",
            headers={"X-API-Key": "good-key"},
            json={"message": "save it", "mode": "synthesis", "previewPrompt": True},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["sessionId"] == f"ghost-{agent_instance_id}"
    assert payload["message"] == "save it"
    assert payload["mode"] == "synthesis"
    assert payload["availableModes"] == ["bootstrap", "build", "synthesis"]
    assert "# Synthesis Mode - System Reminder" in payload["systemPrompt"]
    assert "Your operational mode has changed from plan to build." not in payload["systemPrompt"]
    assert "Existing soul" in payload["systemPrompt"]


@pytest.mark.asyncio
async def test_agents_bootstrap_save_proxies_llm_and_persists_soul(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()

    fake_agent = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "agent_id": f"agent-{agent_instance_id}",
            "name": "Butler",
        },
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id", AsyncMock(return_value=[])
    )
    run_mock = AsyncMock(
        return_value="<SOUL_DRAFT>\n# SOUL\n- Be direct\n</SOUL_DRAFT>"
    )
    monkeypatch.setattr("api.app.run_new_agent_bootstrap_turn", run_mock)
    update_mock = AsyncMock()
    monkeypatch.setattr("api.app.MemoryBlockDAO.update", update_mock)
    create_mock = AsyncMock(return_value=type("Block", (), {"id": uuid4()})())
    monkeypatch.setattr("api.app.MemoryBlockDAO.create", create_mock)

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            f"/api/dashboard/agents/{agent_instance_id}/bootstrap",
            headers={"X-API-Key": "good-key"},
            json={
                "message": "save it",
                "history": [{"role": "assistant", "content": "Tell me more."}],
                "save": True,
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["saved"] is True
    assert payload["soul"] == "# SOUL\n- Be direct"
    assert create_mock.await_count == 1
    assert update_mock.await_count == 0
    assert run_mock.await_args.kwargs["mode"] == "synthesis"


@pytest.mark.asyncio
async def test_agents_bootstrap_save_rejects_invalid_soul_draft(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()

    fake_agent = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "agent_id": f"agent-{agent_instance_id}",
            "name": "Butler",
        },
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "api.app.run_new_agent_bootstrap_turn",
        AsyncMock(return_value="收到，**SOUL.md** 已即時保存並鎖定。"),
    )
    create_mock = AsyncMock(return_value=type("Block", (), {"id": uuid4()})())
    monkeypatch.setattr("api.app.MemoryBlockDAO.create", create_mock)

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            f"/api/dashboard/agents/{agent_instance_id}/bootstrap",
            headers={"X-API-Key": "good-key"},
            json={
                "message": "save it",
                "history": [{"role": "assistant", "content": "Tell me more."}],
                "save": True,
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 502
    assert payload["error"] == "invalid_soul_draft"
    assert create_mock.await_count == 0


@pytest.mark.asyncio
async def test_agents_bootstrap_returns_bad_gateway_on_llm_failure(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()

    fake_agent = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "agent_id": f"agent-{agent_instance_id}",
            "name": "Butler",
        },
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "api.app.run_new_agent_bootstrap_turn",
        AsyncMock(side_effect=RuntimeError("provider timeout")),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            f"/api/dashboard/agents/{agent_instance_id}/bootstrap",
            headers={"X-API-Key": "good-key"},
            json={"message": "hello", "history": [], "save": False},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 502
    assert payload["error"] == "bootstrap_llm_failed"


@pytest.mark.asyncio
async def test_agents_update_upserts_fields_and_memory_blocks(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()
    group_id = uuid4()

    fake_agent_before = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "name": "Old Name",
            "agent_type_id": uuid4(),
            "status": "idle",
            "phone_no": None,
            "whatsapp_key": None,
            "is_sub_agent": False,
            "is_active": True,
            "agent_id": "agent-001",
            "endpoint_group_id": None,
            "created_at": None,
        },
    )()
    fake_agent_after = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "name": "New Name",
            "agent_type_id": uuid4(),
            "status": "idle",
            "phone_no": None,
            "whatsapp_key": None,
            "is_sub_agent": False,
            "is_active": True,
            "agent_id": "agent-001",
            "endpoint_group_id": group_id,
            "created_at": None,
        },
    )()
    fake_block = type(
        "Block",
        (),
        {"id": uuid4(), "memory_type": "SOUL", "content": "old soul"},
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent_before)
    )
    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.update", AsyncMock(return_value=fake_agent_after)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id",
        AsyncMock(return_value=[fake_block]),
    )
    update_mock = AsyncMock(return_value=fake_block)
    monkeypatch.setattr("api.app.MemoryBlockDAO.update", update_mock)
    monkeypatch.setattr("api.app.MemoryBlockDAO.create", AsyncMock(return_value=fake_block))

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.patch(
            f"/api/dashboard/agents/{agent_instance_id}",
            headers={"X-API-Key": "good-key"},
            json={
                "name": "New Name",
                "endpointGroupId": str(group_id),
                "memoryBlocks": {"SOUL": "new soul content"},
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["agent"]["name"] == "New Name"
    assert payload["agent"]["endpointGroupId"] == str(group_id)
    # SOUL existed → update called, not create
    update_mock.assert_called_once()


@pytest.mark.asyncio
async def test_agents_get_memory_blocks_returns_typed_dict(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()

    fake_agent = type(
        "Agent",
        (),
        {"id": agent_instance_id, "user_id": user_id},
    )()
    soul_block = type(
        "Block", (), {"memory_type": "SOUL", "content": "我是助手"}
    )()
    profile_block = type(
        "Block", (), {"memory_type": "USER_PROFILE", "content": "用戶喜歡簡短回答"}
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id",
        AsyncMock(return_value=[soul_block, profile_block]),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get(
            f"/api/dashboard/agents/{agent_instance_id}/memory-blocks",
            headers={"X-API-Key": "good-key"},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["SOUL"] == "我是助手"
    assert payload["USER_PROFILE"] == "用戶喜歡簡短回答"
    assert payload["IDENTITY"] == ""  # not present → empty string
