import logging
from typing import Any

from backend.dao import AgentSessionDAO
from backend.db.session import async_session_factory
from backend.i18n import t

logger = logging.getLogger(__name__)


class Agent:
    _graph: Any = None

    user_db_id: int
    agent_db_id: int
    session_db_id: int

    user_id: str
    agent_id: str
    session_id: str

    agent_type: str

    recv_agent_name: str
    sender_agent_name: str

    stm_trigger_token: int
    stm_summary_token: int

    def __init__(
        self,
        user_db_id: int,
        agent_db_id: int,
        session_db_id: int,
        user_id: str,
        agent_id: str,
        session_id: str,
        agent_type: str,
        recv_agent_name: str,
        sender_agent_name: str,
    ):
        self.agent_db_id = agent_db_id
        self.agent_id = agent_id
        self.session_db_id = session_db_id
        self.session_id = session_id
        self.user_db_id = user_db_id
        self.user_id = user_id
        self.agent_type = agent_type
        self.recv_agent_name = recv_agent_name
        self.sender_agent_name = sender_agent_name

    @classmethod
    async def get_db_agent(
        cls, agent_id: str, session_id: str
    ) -> tuple[int, int, int, str, str, str, str, str, str]:
        async with async_session_factory() as session:
            row = await AgentSessionDAO(session).get_agent_runtime_data(agent_id, session_id)

        if row is None:
            raise LookupError(t("agent.not_found") % (agent_id, session_id))

        return row

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str):
        return cls(*(await cls.get_db_agent(agent_id, session_id)))
