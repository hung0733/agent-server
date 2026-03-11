import asyncio
from typing import Dict, Optional

from sqlalchemy.future import select
from agent.agent import Agent
from db.message_dao import MessageDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent


class AgentV1(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.brain = BrainAgent(self.stream)

    @classmethod
    async def get_agent(
        cls, agent_id: str, session_id: str = "default", stream: bool = True
    ):
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
            stream=stream,
        )

    async def chat(self, user_input: str, is_think_mode: bool = False):
        message_dao = MessageDAO()

        # 使用 DAO 獲取歷史訊息
        historys = []
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            historys = await message_dao.list_by_session(session, self.session_db_id)

        historys_dto = [MessageDTO.from_model(m) for m in historys]

        messages: list[Dict[str, str]] = []

        if self.sys_prompt:
            messages.append({"role": "system", "content": f"{self.sys_prompt}"})

        for m in historys_dto:
            messages.append(m.to_msg())

        user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, is_think_mode)
        messages.append(user_msg.to_msg())

        if self.stream:
            return Agent.handleAsyncGenerator(self, is_think_mode, user_msg, self.brain.send(messages, is_think_mode))
        else:
            return Agent.handleMsgResponse(self, is_think_mode, user_msg, self.brain.send(messages, is_think_mode))