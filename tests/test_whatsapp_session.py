import pytest

from backend.channels.types import ReceivedMessage
from backend.services import whatsapp_session


@pytest.mark.asyncio
async def test_resolve_whatsapp_agent_session_returns_agent_id_and_default_session_id():
    class FakeAgent:
        agent_id = "agent-123e4567-e89b-12d3-a456-426614174000"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scalar(self, stmt):
            return FakeAgent()

    message = ReceivedMessage(
        instance="sales-agent",
        phone_no="85298765432",
        raw={},
    )

    agent_id, session_id = await whatsapp_session.resolve_whatsapp_agent_session(
        message,
        session_factory=FakeSession,
    )

    assert agent_id == "agent-123e4567-e89b-12d3-a456-426614174000"
    assert session_id == "default-123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.asyncio
async def test_resolve_whatsapp_agent_session_returns_none_when_agent_not_found(monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp_session.logger, "warning", lambda *args, **kwargs: calls.append((args, kwargs)))

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scalar(self, stmt):
            return None

    message = ReceivedMessage(
        instance="sales-agent",
        phone_no="85298765432",
        raw={},
    )

    agent_id, session_id = await whatsapp_session.resolve_whatsapp_agent_session(message, session_factory=FakeSession)

    assert agent_id is None
    assert session_id is None
    assert calls[0][1] == {}


@pytest.mark.asyncio
async def test_resolve_whatsapp_agent_session_returns_agent_id_without_session_for_invalid_agent_id(monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp_session.logger, "warning", lambda *args, **kwargs: calls.append((args, kwargs)))

    class FakeAgent:
        agent_id = "legacy-agent"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scalar(self, stmt):
            return FakeAgent()

    message = ReceivedMessage(
        instance="sales-agent",
        phone_no="85298765432",
        raw={},
    )

    agent_id, session_id = await whatsapp_session.resolve_whatsapp_agent_session(message, session_factory=FakeSession)

    assert agent_id == "legacy-agent"
    assert session_id is None
    assert calls
