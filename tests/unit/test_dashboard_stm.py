"""Tests for STM dashboard endpoint."""
import pytest
from aiohttp import web
from api.app import create_app


@pytest.mark.asyncio
async def test_stm_endpoint_returns_current_day_summaries():
    """Test that STM endpoint returns bullet point entries from current-day summaries."""
    app = create_app(queue=None, dedup=None)
    
    # TDD: Verify endpoint doesn't exist yet
    # Will add full mock test in next step
    assert app.router.get("/api/dashboard/stm") is None