from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.llm_group import LlmGroup


class LlmGroupDAO(BaseDAO[LlmGroup]):
    model = LlmGroup

    async def list_by_user_id(self, user_id: int) -> list[LlmGroup]:
        stmt = select(LlmGroup).where(LlmGroup.user_id == user_id)
        result = await self.session.scalars(stmt)
        return list(result)
