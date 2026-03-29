from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer

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
        return {"locales": ["zh-HK"], "source": "mock"}


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
