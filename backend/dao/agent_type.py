from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.agent_type import AgentType


class AgentTypeDAO(BaseDAO[AgentType]):
    model = AgentType

    async def get_by_code(self, code: str) -> AgentType | None:
        stmt = select(AgentType).where(AgentType.code == code)
        return await self.session.scalar(stmt)

    async def get_or_create_by_code(self, code: str, name: str | None = None) -> AgentType:
        code = code.strip()
        agent_type = await self.get_by_code(code)
        if agent_type is not None:
            return agent_type

        agent_type = AgentType(code=code, name=name or code)
        self.session.add(agent_type)
        await self.session.flush()
        await self.session.refresh(agent_type)
        return agent_type
