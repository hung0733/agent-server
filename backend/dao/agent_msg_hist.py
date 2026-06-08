from datetime import datetime

from sqlalchemy import func, select

from backend.dao.base import BaseDAO
from backend.entities.agent_msg_hist import AgentMsgHist


class AgentMsgHistDAO(BaseDAO[AgentMsgHist]):
    model = AgentMsgHist

    async def list_by_session_id(self, session_id: int) -> list[AgentMsgHist]:
        stmt = (
            select(AgentMsgHist)
            .where(AgentMsgHist.session_id == session_id)
            .order_by(AgentMsgHist.create_dt)
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def count_by_session_id(self, session_id: int) -> int:
        stmt = select(func.count()).select_from(AgentMsgHist).where(
            AgentMsgHist.session_id == session_id
        )
        return int(await self.session.scalar(stmt) or 0)

    async def exists_duplicate(
        self,
        *,
        session_id: int,
        sender: str,
        msg_type: str,
        content: str | None,
        meta_data: str | None,
        create_dt: datetime | None,
    ) -> bool:
        stmt = (
            select(AgentMsgHist.id)
            .where(
                AgentMsgHist.session_id == session_id,
                AgentMsgHist.sender == sender,
                AgentMsgHist.msg_type == msg_type,
                AgentMsgHist.content == content,
                AgentMsgHist.meta_data == meta_data,
                AgentMsgHist.create_dt == create_dt,
            )
            .limit(1)
        )
        return await self.session.scalar(stmt) is not None
