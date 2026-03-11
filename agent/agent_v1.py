from typing import Optional

from agent.agent import Agent
from dto.agent import AgentDTO
from dto.session import SessionDTO
from llm.brain_agent import BrainAgent


class AgentV1(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = BrainAgent(self.stream)

    @classmethod
    async def get_agent(
        cls, agent_id: str, session_id: str = "default", stream: bool = True
    ):
        agent: Optional[AgentDTO] = None
        session: Optional[SessionDTO] = None

        agent, session = await Agent.get_db_agent(agent_id, session_id)

        # 攞到資料，返傳實例
        return cls(
            db_id=agent.id,
            agent_id=agent.agent_id,
            session_db_id=session.id,
            session_id=session.session_id,
            name=agent.name,
            sys_prompt=agent.sys_prompt,
            stream=stream,
        )
