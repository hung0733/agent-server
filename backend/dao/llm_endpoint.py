from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.llm_endpoint import LlmEndpoint


class LlmEndpointDAO(BaseDAO[LlmEndpoint]):
    model = LlmEndpoint

    async def list_by_user_id(self, user_id: int) -> list[LlmEndpoint]:
        stmt = select(LlmEndpoint).where(LlmEndpoint.user_id == user_id)
        result = await self.session.scalars(stmt)
        return list(result)
