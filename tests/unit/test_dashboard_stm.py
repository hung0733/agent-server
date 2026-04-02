"""Tests for STM dashboard endpoint."""
import pytest
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone
from api.app import create_app


class _FakeQueue:
    def qsize(self) -> int:
        return 0


class _FakeDedup:
    size = 0


class _FakeAuthService:
    def __init__(self, user_id):
        self.user_id = user_id

    async def authenticate(self, raw_key: str):
        if raw_key == "good-key":
            return {"user_id": self.user_id}
        return None


@pytest.mark.asyncio
async def test_stm_endpoint_exists_and_returns_stm_data():
    """Test that STM endpoint exists and returns correct contract."""
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        auth_service=_FakeAuthService(user_id),
    )
    
    stm_routes = [r for r in app.router.routes() if str(r.resource.canonical) == "/api/dashboard/stm"]
    assert len(stm_routes) >= 1


@pytest.mark.asyncio
async def test_stm_endpoint_returns_current_day_summaries():
    """Test that STM endpoint returns bullet point entries from current-day summaries."""
    user_id = uuid4()
    
    mock_agent_1 = MagicMock()
    mock_agent_1.id = uuid4()
    mock_agent_2 = MagicMock()
    mock_agent_2.id = uuid4()
    
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall = AsyncMock(return_value=[
        (
            "session-test-1",
            "checkpoint-001",
            "- First bullet point\n- Second bullet point",
            "2026-04-03T10:00:00Z"
        ),
    ])
    mock_conn.execute.return_value = mock_result
    
    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_pool.connection.return_value = mock_conn
    
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)
    
    await client.start_server()
    try:
        with patch("api.dashboard_stm.AgentInstanceDAO.get_by_user_id", AsyncMock(return_value=[mock_agent_1, mock_agent_2])):
            with patch("api.dashboard_stm.GraphStore.pool", mock_pool):
                response = await client.get("/api/dashboard/stm", headers={"X-API-Key": "good-key"})
                payload = await response.json()
    finally:
        await client.close()
    
    assert response.status == 200
    assert "entries" in payload
    assert "hasMore" in payload
    assert "source" in payload
    assert payload["source"] == "langgraph"
    assert isinstance(payload["entries"], list)


@pytest.mark.asyncio
async def test_stm_endpoint_requires_auth():
    """Test that STM endpoint requires authentication."""
    app = create_app(_FakeQueue(), _FakeDedup())
    server = TestServer(app)
    client = TestClient(server)
    
    await client.start_server()
    try:
        response = await client.get("/api/dashboard/stm")
        payload = await response.json()
    finally:
        await client.close()
    
    assert response.status == 401
    assert payload["error"] == "unauthorized"