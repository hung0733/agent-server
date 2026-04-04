from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from datetime import datetime, timezone

import pytest

from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dto.collaboration_dto import CollaborationSessionCreate
from db.types import CollaborationStatus


@pytest.mark.asyncio
async def test_create_persists_sender_agent_id() -> None:
    user_id = uuid4()
    main_agent_id = uuid4()
    sender_agent_id = uuid4()

    fake_session = SimpleNamespace(
        add=lambda entity: None,
        flush=AsyncMock(),
        refresh=AsyncMock(
            side_effect=lambda entity: [
                setattr(entity, "id", uuid4()),
                setattr(entity, "created_at", datetime.now(timezone.utc)),
                setattr(entity, "updated_at", datetime.now(timezone.utc)),
            ]
        ),
    )

    dto = CollaborationSessionCreate(
        user_id=user_id,
        main_agent_id=main_agent_id,
        sender_agent_id=sender_agent_id,
        session_id="session-test",
        status=CollaborationStatus.active,
    )

    result = await CollaborationSessionDAO.create(dto, session=fake_session)

    assert result.sender_agent_id == sender_agent_id


@pytest.mark.asyncio
async def test_get_private_session_returns_matching_active_session(monkeypatch) -> None:
    user_id = uuid4()
    sender_agent_id = uuid4()
    main_agent_id = uuid4()
    entity = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        main_agent_id=main_agent_id,
        sender_agent_id=sender_agent_id,
        session_id="session-private",
        name="private",
        status=CollaborationStatus.active,
        involves_secrets=False,
        context_json=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        ended_at=None,
    )
    fake_result = SimpleNamespace(scalar_one_or_none=lambda: entity)
    fake_session = SimpleNamespace(execute=AsyncMock(return_value=fake_result))

    result = await CollaborationSessionDAO.get_private_session(
        user_id=user_id,
        sender_agent_id=sender_agent_id,
        main_agent_id=main_agent_id,
        session=fake_session,
    )

    assert result is not None
    assert result.session_id == "session-private"


@pytest.mark.asyncio
async def test_get_private_session_returns_none_when_no_match() -> None:
    fake_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    fake_session = SimpleNamespace(execute=AsyncMock(return_value=fake_result))

    result = await CollaborationSessionDAO.get_private_session(
        user_id=uuid4(),
        sender_agent_id=uuid4(),
        main_agent_id=uuid4(),
        session=fake_session,
    )

    assert result is None
