"""Tests for LTM dashboard endpoint."""
import pytest
from aiohttp.test_utils import TestClient, TestServer
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
async def test_ltm_endpoint_does_not_exist_yet():
    """TDD placeholder: LTM endpoint not yet implemented."""
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        auth_service=_FakeAuthService(user_id),
    )
    
    ltm_routes = [r for r in app.router.routes() if str(r.resource.canonical) == "/api/dashboard/ltm"]
    assert len(ltm_routes) == 0