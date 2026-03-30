from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer

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


class _FakeAuthService:
    def __init__(self, user_id):
        self.user_id = user_id

    async def authenticate(self, raw_key: str):
        if raw_key == "good-key":
            return {"user_id": self.user_id}
        return None


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
