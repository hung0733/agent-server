from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.memory_block import MemoryBlock


class MemoryBlockDAO(BaseDAO[MemoryBlock]):
    model = MemoryBlock

    async def list_by_agent_id(self, agent_id: int) -> list[MemoryBlock]:
        stmt = select(MemoryBlock).where(MemoryBlock.agent_id == agent_id).order_by(MemoryBlock.last_upd_dt)
        result = await self.session.scalars(stmt)
        return list(result)
