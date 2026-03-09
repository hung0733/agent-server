import asyncio
from typing import AsyncGenerator, Dict, Iterable
import uuid

from sqlalchemy.future import select
from db.models import AgentModel, MessageModel, SessionModel
from dto.message import MessageDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent


class AgentV1:
    _pending_tasks = set() # 紀錄未完成嘅儲存任務
    
    def __init__(
        self,
        db_id: int,
        agent_id: str,
        session_db_id: int,
        session_id: str,
        name: str,
        sys_prompt: str
    ):
        self.db_id = db_id
        self.agent_id = agent_id
        self.session_db_id = session_db_id
        self.session_id = session_id
        self.name = name
        self.sys_prompt = sys_prompt
        self.brain = BrainAgent()

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str = "default"):
        """
        喺 DB 攞資料並初始化 Agent
        """
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            # 喺 DB 搵對應嘅 agent_id
            query = select(AgentModel).where(AgentModel.agent_id == agent_id)
            result = await session.execute(query)
            db_agent: AgentModel = result.scalars().first()

            if not db_agent:
                print(f"⚠️ Agent {agent_id} 唔存在喺資料庫。")
                return None

            query = select(SessionModel).where(
                SessionModel.agent_id == db_agent.id
                and SessionModel.session_id == session_id
            )
            result = await session.execute(query)
            db_session: SessionModel = result.scalars().first()

            if not db_agent:
                print(f"⚠️ Session {session_id} 唔存在喺資料庫。")
                return None

            # 攞到資料，返傳實例
            return cls(
                db_id=db_agent.id,  # type: ignore
                agent_id=db_agent.agent_id,  # type: ignore
                session_db_id=db_session.id,
                session_id=session_id,
                name=db_agent.name,  # type: ignore
                sys_prompt=db_agent.sys_prompt  # type: ignore
            )

    async def chat(self, user_input: str, is_think_mode: bool = False):
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            query = (
                select(MessageModel)
                .where(
                    MessageModel.agent_id == self.db_id
                    and MessageModel.session_id == self.session_db_id
                )
                .order_by(MessageModel.create_date.asc())
            )
            result = await session.execute(query)
            historys: list[MessageDTO] = [
                MessageDTO.get(m) for m in (result.scalars().all() or [])
            ]

            messages: list[Dict[str, str]] = []

            if self.sys_prompt:
                messages.append({"role": "system", "content": f"{self.sys_prompt}"})

            for m in historys:
                messages.append(m.to_msg())

            pend_save: list[MessageDTO] = []

            user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, is_think_mode)
            pend_save.append(user_msg)
            messages.append(user_msg.to_msg())

            print(f"🤖 Agent [{self.name}] 思考中...")

            raw_response = self.brain.send(messages, is_think_mode)

            # 4. 定義內部 Async Generator 嚟處理唔同型別同埋背景儲存
            async def wrapped_generator() -> AsyncGenerator[str, None]:
                full_content = ""
                full_reasoning = ""
                is_currently_reasoning = False

                if isinstance(raw_response, Iterable):
                    for chunk in raw_response:
                        if not isinstance(chunk, str):
                            continue

                        # 標籤解析邏輯
                        if chunk == "<think>":
                            is_currently_reasoning = True
                            yield "---------- 思考中 ----------"
                            continue  # 唔使 yield 俾 User
                        elif chunk == "</think>":
                            is_currently_reasoning = False
                            yield "---------------------------"
                            continue  # 唔使 yield 俾 User

                        if is_currently_reasoning:
                            full_reasoning += chunk
                            yield chunk
                        else:
                            full_content += chunk
                            yield chunk

                if full_reasoning:
                    pend_save.append(
                        MessageDTO.get_reasoning_msg(full_reasoning, is_think_mode)
                    )
                pend_save.append(
                    MessageDTO.get_assistant_msg(full_content, is_think_mode)
                )

                task = asyncio.create_task(MessageDTO.save_message(self, pend_save))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard) # 行完就剔除

            return wrapped_generator()
