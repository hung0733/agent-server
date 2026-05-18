from sqlalchemy import case, select

from backend.dao.base import BaseDAO
from backend.entities.memory_block import MemoryBlock


class MemoryBlockDAO(BaseDAO[MemoryBlock]):
    model = MemoryBlock

    async def list_by_agent_id(self, agent_id: int) -> list[MemoryBlock]:
        stmt = select(MemoryBlock).where(MemoryBlock.agent_id == agent_id).order_by(MemoryBlock.last_upd_dt)
        result = await self.session.scalars(stmt)
        return list(result)

    async def list_by_agent_id_and_memory_types(
        self, agent_id: int, memory_types: tuple[str, ...]
    ) -> list[MemoryBlock]:
        memory_type_order = case(
            {memory_type: index for index, memory_type in enumerate(memory_types)},
            value=MemoryBlock.memory_type,
            else_=len(memory_types),
        )
        stmt = (
            select(MemoryBlock)
            .where(
                MemoryBlock.agent_id == agent_id,
                MemoryBlock.memory_type.in_(memory_types),
            )
            .order_by(memory_type_order, MemoryBlock.last_upd_dt)
        )
        result = await self.session.scalars(stmt)
        return list(result)
