from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from api.app import create_app


class _FakeQueue:
    def qsize(self) -> int:
        return 3


class _FakeDedup:
    size = 7


class _FakeDashboardProvider:
    async def get_overview(self) -> dict:
        return {"summary": {"headline": "ok"}, "source": "mixed"}

    async def get_usage(self) -> dict:
        return {"total": 42, "items": [], "source": "mixed"}

    async def get_agents(self) -> dict:
        return {"agents": [{"id": "main"}], "source": "mixed"}

    async def get_tasks(self) -> dict:
        return {"items": [{"id": "evt-1"}], "source": "mixed"}

    async def get_memory(self) -> dict:
        return {"title": "memory", "source": "mock"}

    async def get_settings(self) -> dict:
        return {"locales": ["zh-HK"], "source": "mock"}


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
    app = create_app(_FakeQueue(), _FakeDedup(), dashboard_data_provider=_FakeDashboardProvider())
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get("/api/dashboard/overview")
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["summary"]["headline"] == "ok"
    assert payload["source"] == "mixed"


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
