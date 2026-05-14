from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.agent_msg_hist import AgentMsgHist


class AgentMsgHistDAO(BaseDAO[AgentMsgHist]):
    model = AgentMsgHist

    async def list_by_session_id(self, session_id: int) -> list[AgentMsgHist]:
        stmt = select(AgentMsgHist).where(AgentMsgHist.session_id == session_id).order_by(AgentMsgHist.create_dt)
        result = await self.session.scalars(stmt)
        return list(result)
