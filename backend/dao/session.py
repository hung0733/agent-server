from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from backend.dao.base import BaseDAO
from backend.entities.agent import Agent
from backend.entities.agent_type import AgentType
from backend.entities.session import AgentSession
from backend.entities.user_acc import UserAcc


class AgentSessionDAO(BaseDAO[AgentSession]):
    model = AgentSession

    async def get_by_session_id(self, session_id: str) -> AgentSession | None:
        stmt = select(AgentSession).where(AgentSession.session_id == session_id)
        return await self.session.scalar(stmt)

    async def list_by_agent_id(self, agent_id: int) -> list[AgentSession]:
        stmt = select(AgentSession).where(
            (AgentSession.recv_agent_id == agent_id) | (AgentSession.sender_agent_id == agent_id)
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def get_default_session_by_agent_db_id(
        self, agent_db_id: int
    ) -> AgentSession | None:
        stmt = (
            select(AgentSession)
            .where(
                AgentSession.recv_agent_id == agent_db_id,
                AgentSession.sender_agent_id.is_(None),
                AgentSession.session_type == "default",
            )
            .order_by(AgentSession.id.asc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def get_agent_runtime_data(
        self, agent_id: str, session_id: str
    ) -> tuple[
        int,
        int,
        int,
        str,
        str,
        str,
        str,
        str,
        str,
        str | None,
        str,
        int | None,
        int | None,
        str | None,
        bool,
        bool,
    ] | None:
        recv_agent = aliased(Agent)
        sender_agent = aliased(Agent)
        sender_default_session = aliased(AgentSession)
        recv_agent_type = aliased(AgentType)
        stmt = (
            select(
                UserAcc.id,
                recv_agent.id,
                AgentSession.id,
                UserAcc.user_id,
                UserAcc.name,
                recv_agent.agent_id,
                AgentSession.session_id,
                recv_agent_type.code,
                recv_agent.name,
                sender_agent.agent_id,
                func.coalesce(sender_agent.name, UserAcc.name),
                sender_agent.id,
                sender_default_session.id,
                sender_default_session.session_id,
                func.coalesce(sender_agent.is_sub_agent, False),
                recv_agent.is_sub_agent,
            )
            .join(recv_agent, AgentSession.recv_agent_id == recv_agent.id)
            .join(recv_agent_type, recv_agent.agent_type_id == recv_agent_type.id)
            .outerjoin(sender_agent, AgentSession.sender_agent_id == sender_agent.id)
            .outerjoin(
                sender_default_session,
                (sender_default_session.recv_agent_id == sender_agent.id)
                & (sender_default_session.sender_agent_id.is_(None))
                & (sender_default_session.session_type == "default"),
            )
            .join(UserAcc, recv_agent.user_id == UserAcc.id)
            .where(
                recv_agent.agent_id == agent_id,
                AgentSession.session_id == session_id,
            )
        )
        row = (await self.session.execute(stmt)).one_or_none()
        return tuple(row) if row is not None else None
