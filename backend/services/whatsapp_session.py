from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy import select

from backend.channels.types import ReceivedMessage
from backend.db.session import async_session_factory
from backend.entities.agent import Agent
from backend.entities.user_acc import UserAcc
from backend.i18n import t


logger = logging.getLogger(__name__)


async def resolve_whatsapp_agent_session(
    message: ReceivedMessage,
    session_factory: Callable[[], Any] = async_session_factory,
) -> tuple[str | None, str | None]:
    if not message.phone_no or not message.instance:
        logger.warning(
            t("main.whatsapp_session_lookup_missing_fields"),
            message.phone_no,
            message.instance,
        )
        return None, None

    stmt = (
        select(Agent)
        .join(UserAcc, Agent.user_id == UserAcc.id)
        .where(
            UserAcc.phoneno == message.phone_no,
            Agent.whatsapp_instance == message.instance,
            Agent.is_active.is_(True),
        )
        .limit(1)
    )

    try:
        async with session_factory() as session:
            agent = await session.scalar(stmt)
    except Exception:
        logger.warning(
            t("main.whatsapp_session_lookup_failed"),
            message.phone_no,
            message.instance,
            exc_info=True,
        )
        return None, None

    if not agent:
        logger.warning(
            t("main.whatsapp_session_not_found"),
            message.phone_no,
            message.instance,
        )
        return None, None

    if not agent.agent_id.startswith("agent-"):
        logger.warning(t("main.whatsapp_session_invalid_agent_id"), agent.agent_id)
        return agent.agent_id, None

    agent_uuid = agent.agent_id.removeprefix("agent-")
    return agent.agent_id, f"default-{agent_uuid}"
