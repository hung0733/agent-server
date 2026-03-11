import asyncio
from typing import AsyncGenerator, Dict, Optional, Union
from fastapi import HTTPException

from sqlalchemy.future import select
from agent.agent import Agent
from db.conn_pool import ConnPool
from db.message_dao import MessageDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent
from openai.types.chat import ChatCompletion, ChatCompletionChunk  # 匯入類型定義


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

        # 檢查 agent 是否存在
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        
        # 檢查 session 是否存在
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found for Agent '{agent_id}'")

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

    async def chat(
        self, user_input: str, is_think_mode: bool = False
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        message_dao = MessageDAO()

        # 1. 獲取歷史紀錄
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            historys = await message_dao.list_by_session(session, self.session_db_id)

        # 2. 構建 messages
        messages: list[Dict[str, str]] = []
        if self.sys_prompt:
            # 確保 sys_prompt 是字串而非 tuple
            prompt_str = (
                self.sys_prompt[0]
                if isinstance(self.sys_prompt, tuple)
                else self.sys_prompt
            )
            messages.append({"role": "system", "content": prompt_str})

        for m in historys:
            messages.append(MessageDTO.from_model(m).to_msg())

        # 加入使用者當前輸入
        user_msg_dto = MessageDTO.get_user_msg(user_input, is_think_mode)
        messages.append(user_msg_dto.to_msg())

        return self.handleMsgResponse(self, is_think_mode, user_msg_dto, await self.brain.send(messages, is_think_mode))
