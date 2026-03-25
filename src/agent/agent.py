import logging
from typing import List
from db.dto.memory_block_dto import MemoryBlock
from i18n import _

logger = logging.getLogger(__name__)


class Agent:
    agent_db_id: str
    session_db_id: str

    agent_id: str
    session_id: str
    name: str
    involves_secrets: bool = False

    stm_trigger_token: int
    stm_summary_token: int

    def __init__(
        self,
        agent_db_id: str,
        session_db_id: str,
        agent_id: str,
        session_id: str,
        involves_secrets: bool,
        name: str,
    ):
        self.agent_db_id = agent_db_id
        self.session_db_id = session_db_id

        self.agent_id = agent_id
        self.session_id = session_id
        self.involves_secrets = involves_secrets
        self.name = name

    @staticmethod
    async def get_db_agent(agent_id: str, session_id: str):
        from db.dao.collaboration_session_dao import CollaborationSessionDAO
        from db.entity.agent_entity import AgentInstance as AgentInstanceEntity
        from sqlalchemy import select
        from db import create_engine, AsyncSession, async_sessionmaker

        # Resolve agent_id string → AgentInstance DB row
        engine = create_engine()
        async_session = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session() as s:
            result = await s.execute(
                select(AgentInstanceEntity).where(
                    AgentInstanceEntity.agent_id == agent_id
                )
            )
            agent_entity = result.scalar_one_or_none()
        await engine.dispose()

        if agent_entity is None:
            raise ValueError(_("Agent not found: %s") % agent_id)

        # Resolve session_id string → CollaborationSession DB row
        collab = await CollaborationSessionDAO.get_by_session_id(session_id)
        if collab is None:
            raise ValueError(_("Session not found: %s") % session_id)

        return (
            str(agent_entity.id),
            str(collab.id),
            agent_id,
            session_id,
            collab.involves_secrets,
            agent_entity.name or agent_id,
        )

    async def get_memory_prompt(self) -> str:
        """Retrieve all active memory blocks for this agent from the DB.

        Returns:
            List of MemoryBlock DTOs for this agent.
        """
        from db.dao.memory_block_dao import MemoryBlockDAO
        from uuid import UUID

        mb_list: List[MemoryBlock] = await MemoryBlockDAO.get_by_agent_instance_id(
            UUID(self.agent_db_id)
        )

        prompt: str = ""
        for mb in mb_list:
            prompt += (
                f"<{mb.memory_type}>\n\n" + mb.content + f"\n\n</{mb.memory_type}>\n\n"
            )
            
        return prompt
