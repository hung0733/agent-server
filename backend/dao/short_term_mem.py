from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.short_term_mem import ShortTermMem


class ShortTermMemDAO(BaseDAO[ShortTermMem]):
    model = ShortTermMem

    async def list_by_session_id(self, session_id: int) -> list[ShortTermMem]:
        stmt = select(ShortTermMem).where(ShortTermMem.session_id == session_id).order_by(ShortTermMem.create_dt)
        result = await self.session.scalars(stmt)
        return list(result)
