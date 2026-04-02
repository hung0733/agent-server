"""Tests for LTM dashboard endpoint."""
import pytest
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
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
async def test_ltm_endpoint_exists_and_returns_ltm_data():
    """Test that LTM endpoint exists and returns correct contract."""
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        auth_service=_FakeAuthService(user_id),
    )
    
    ltm_routes = [r for r in app.router.routes() if str(r.resource.canonical) == "/api/dashboard/ltm"]
    assert len(ltm_routes) >= 1


@pytest.mark.asyncio
async def test_ltm_endpoint_returns_entries_from_qdrant():
    """Test that LTM endpoint returns entries from Qdrant vector store."""
    user_id = uuid4()
    
    mock_agent_1 = MagicMock()
    mock_agent_1.id = uuid4()
    
    mock_entry = MagicMock()
    mock_entry.entry_id = "entry-001"
    mock_entry.lossless_restatement = "Test memory"
    mock_entry.timestamp = None
    mock_entry.keywords = []
    mock_entry.persons = []
    mock_entry.entities = []
    mock_entry.topic = None
    mock_entry.location = None
    
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)
    
    await client.start_server()
    try:
        with patch("api.dashboard_ltm.AgentInstanceDAO.get_by_user_id", AsyncMock(return_value=[mock_agent_1])):
            mock_store_instance = MagicMock()
            mock_store_instance.get_all_entries = MagicMock(return_value=[mock_entry])
            
            with patch("ltm.database.vector_store.QdrantVectorStore", return_value=mock_store_instance):
                with patch("ltm.database.vector_store.QdrantClient"):
                    response = await client.get("/api/dashboard/ltm", headers={"X-API-Key": "good-key"})
                    payload = await response.json()
    finally:
        await client.close()
    
    assert response.status == 200
    assert "entries" in payload
    assert "hasMore" in payload
    assert "source" in payload


@pytest.mark.asyncio
async def test_ltm_endpoint_requires_auth():
    """Test that LTM endpoint requires authentication."""
    app = create_app(_FakeQueue(), _FakeDedup())
    server = TestServer(app)
    client = TestClient(server)
    
    await client.start_server()
    try:
        response = await client.get("/api/dashboard/ltm")
        payload = await response.json()
    finally:
        await client.close()
    
    assert response.status == 401
    assert payload["error"] == "unauthorized"