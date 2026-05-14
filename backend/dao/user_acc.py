from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.user_acc import UserAcc


class UserAccDAO(BaseDAO[UserAcc]):
    model = UserAcc

    async def get_by_user_id(self, user_id: str) -> UserAcc | None:
        stmt = select(UserAcc).where(UserAcc.user_id == user_id)
        return await self.session.scalar(stmt)
