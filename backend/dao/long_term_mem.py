from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.long_term_mem import LongTermMem


class LongTermMemDAO(BaseDAO[LongTermMem]):
    model = LongTermMem

    async def list_by_agent_id(self, agent_id: int) -> list[LongTermMem]:
        stmt = select(LongTermMem).where(LongTermMem.agent_id == agent_id).order_by(LongTermMem.create_dt)
        result = await self.session.scalars(stmt)
        return list(result)
