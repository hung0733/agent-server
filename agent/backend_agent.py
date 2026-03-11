import asyncio
import re
from typing import Dict, Optional

from sqlalchemy.future import select
from agent.agent import Agent
from db.conn_pool import ConnPool
from db.long_term_memory_dao import LongTermMemoryDAO
from db.prompt_dao import PromptDAO
from dto.agent import AgentDTO
from dto.long_term_memory import LongTermMemoryDTO
from dto.message import MessageDTO
from dto.prompt import PromptDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent


class BackendAgent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = BrainAgent(self.stream)

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str):
        agent: Optional[AgentDTO] = None
        session: Optional[SessionDTO] = None

        agent, session = await Agent.get_db_agent(agent_id, session_id)

        if agent and session:
            # 攞到資料，返傳實例
            return cls(
                db_id=agent.id,  # type: ignore
                agent_id=agent.agent_id,  # type: ignore
                session_db_id=session.id,
                session_id=session.session_id,
                name=agent.name,  # type: ignore
                sys_prompt=agent.sys_prompt,  # type: ignore
                stream=True,
            )
        return None

    async def summary(self, msg_list: list[MessageDTO]):
        dto: PromptDTO
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            dto = PromptDTO.from_model(
                await PromptDAO().get_by_code(session, "summary")
            )

        sys_prompt: str = dto.prompt
        retry_prompt: str = dto.retry_prompt

        for i in range(3):
            temperature: float = 0.1 * i
            if i == 2:
                sys_prompt = retry_prompt

            user_input: str = ""
            for msg in msg_list:
                if msg.msg_type in ["user_message", "assistant_message"]:
                    user_input += msg.date.isoformat(sep=" ", timespec="seconds") + "\n"
                    user_input += msg.sent_by + "\n"
                    user_input += msg.content + "\n\n"

            messages: list[MessageDTO] = []
            messages.append({"role": "system", "content": sys_prompt})
            user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, True)
            messages.append(user_msg.to_msg())

            content: str = ""

            (
                _,
                content,
            ) = await self.getResponse(
                agent=self,
                response=await self.send(
                    messages=messages,
                    user_msg=user_msg,
                    is_think_mode=True,
                    temperature=temperature,
                ),
            )

            if content:
                content = re.sub(r"```json|```", "", content)
                ConnPool.start_db_async_task(
                    LongTermMemoryDAO().save_memory(
                        agent=self,
                        mem=LongTermMemoryDTO(
                            content: Dict[str, Any]
                        vector_content: str | None
                        importance: int
                        created_at: datetime | None
                        ),
                        message_db_ids=[msg.id for msg in msg_list or []],
                    )
                )
                break
