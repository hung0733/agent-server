import asyncio
from typing import Dict, Optional

from sqlalchemy.future import select
from agent.agent import Agent
from dto.agent import AgentDTO
from dto.session import SessionDTO
from llm.brain_agent import BrainAgent


class BackendAgent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.brain = BrainAgent(self.stream)

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str):
        agent: Optional[AgentDTO] = None
        session: Optional[SessionDTO] = None

        agent, session = await Agent.get_db_agent(agent_id, session_id)

        # 攞到資料，返傳實例
        return cls(
            db_id=agent.id,  # type: ignore
            agent_id=agent.agent_id,  # type: ignore
            session_db_id=session.id,
            session_id=session.session_id,
            name=agent.name,  # type: ignore
            sys_prompt=agent.sys_prompt,  # type: ignore
            stream=False,
        )
