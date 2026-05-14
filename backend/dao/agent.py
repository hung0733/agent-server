from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.agent import Agent


class AgentDAO(BaseDAO[Agent]):
    model = Agent

    async def get_by_agent_id(self, agent_id: str) -> Agent | None:
        stmt = select(Agent).where(Agent.agent_id == agent_id)
        return await self.session.scalar(stmt)

    async def list_by_user_id(self, user_id: int) -> list[Agent]:
        stmt = select(Agent).where(Agent.user_id == user_id)
        result = await self.session.scalars(stmt)
        return list(result)
