from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.llm_level import LlmLevel


class LlmLevelDAO(BaseDAO[LlmLevel]):
    model = LlmLevel

    async def list_by_llm_group_id(self, llm_group_id: int) -> list[LlmLevel]:
        stmt = select(LlmLevel).where(LlmLevel.llm_group_id == llm_group_id).order_by(LlmLevel.level, LlmLevel.seq_no)
        result = await self.session.scalars(stmt)
        return list(result)
