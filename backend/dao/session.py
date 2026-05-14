from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.session import AgentSession


class AgentSessionDAO(BaseDAO[AgentSession]):
    model = AgentSession

    async def get_by_session_id(self, session_id: str) -> AgentSession | None:
        stmt = select(AgentSession).where(AgentSession.session_id == session_id)
        return await self.session.scalar(stmt)

    async def list_by_agent_id(self, agent_id: int) -> list[AgentSession]:
        stmt = select(AgentSession).where(
            (AgentSession.recv_agent_id == agent_id) | (AgentSession.sender_agent_id == agent_id)
        )
        result = await self.session.scalars(stmt)
        return list(result)
