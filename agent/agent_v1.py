import asyncio
from typing import AsyncGenerator, Dict, Iterable, Tuple
import uuid

from sqlalchemy.future import select
from db.conn_pool import ConnPool
from db.models import AgentModel, MessageModel, SessionModel
from db.agent_dao import AgentDAO
from db.session_dao import SessionDAO
from db.message_dao import MessageDAO
from dto.message import MessageDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent
import tiktoken


class AgentV1:
    def __init__(
        self,
        db_id: int,
        agent_id: str,
        session_db_id: int,
        session_id: str,
        name: str,
        sys_prompt: str,
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
        喺 DB 攞資料並初始化 Agent (使用 DAO)
        """
        agent_dao = AgentDAO()
        session_dao = SessionDAO()

        # 喺 DB 搵對應嘅 agent_id 同 session
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            db_agent = await agent_dao.get_by_agent_id(session, agent_id)

            if not db_agent:
                print(f"⚠️ Agent {agent_id} 唔存在喺資料庫。")
                return None

            # 根據 session_id 獲取 Session (default 需要配合 agent_db_id，其他可以單獨查找)
            if session_id == "default":
                db_session = await session_dao.get_default_session(session, db_agent.id)
            else:
                db_session = await session_dao.get_by_session_id(session, session_id)

            if not db_session:
                print(f"⚠️ Session {session_id} 唔存在喺資料庫。")
                return None

        # 攞到資料，返傳實例
        return cls(
            db_id=db_agent.id,  # type: ignore
            agent_id=db_agent.agent_id,  # type: ignore
            session_db_id=db_session.id,
            session_id=session_id,
            name=db_agent.name,  # type: ignore
            sys_prompt=db_agent.sys_prompt,  # type: ignore
        )

    async def chat(self, user_input: str, is_think_mode: bool = False):
        message_dao = MessageDAO()
        
        # 使用 DAO 獲取歷史訊息
        historys = []
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            historys = await message_dao.list_by_session(
                session,
                self.session_db_id
            )
        
        historys_dto = [MessageDTO.from_model(m) for m in historys]

        messages: list[Dict[str, str]] = []

        if self.sys_prompt:
            messages.append({"role": "system", "content": f"{self.sys_prompt}"})

        for m in historys_dto:
            messages.append(m.to_msg())

        pend_save: list[MessageDTO] = []

        user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, is_think_mode)
        pend_save.append(user_msg)
        messages.append(user_msg.to_msg())

        print(f"\n🤖 Agent [{self.name}] 思考中...\n")

        # 4. 調用 brain.send() 獲取 async generator（因為 send 已經是 async def）
        raw_response_gen = self.brain.send(messages, is_think_mode)

        # 5. 定義內部 Async Generator 嚟處理背景儲存
        async def wrapped_generator():
            full_reasoning = ""
            full_content = ""
            
            # 使用 async for 遍歷 raw_response_gen（因為它已經是 async generator）
            async for chunk in raw_response_gen:
                yield chunk
                
                # 收集 content 同 reasoning 用於保存
                if hasattr(chunk, 'choices') and chunk.choices:
                    delta = chunk.choices[0].delta
                    
                    # 提取 reasoning_content
                    reasoning = getattr(delta, 'reasoning_content', None)
                    if reasoning:
                        full_reasoning += reasoning
                    
                    # 提取 content
                    if delta.content:
                        full_content += delta.content

            
            if full_reasoning:
                pend_save.append(
                    MessageDTO.get_reasoning_msg(full_reasoning, is_think_mode)
                )
                
            pend_save.append(
                MessageDTO.get_assistant_msg(full_content, is_think_mode)
            )

            ConnPool.start_db_async_task(self._save_messages_to_db(pend_save))

        return wrapped_generator()

    async def chat_non_stream(self, user_input: str, is_think_mode: bool = False):
        """非串流聊天方法，返回 (reasoning_content, content)"""
        message_dao = MessageDAO()
        
        # 使用 DAO 獲取歷史訊息
        historys = []
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            historys = await message_dao.list_by_session(
                session,
                self.session_db_id
            )
        historys_dto = [MessageDTO.from_model(m) for m in historys]

        messages: list[Dict[str, str]] = []

        if self.sys_prompt:
            messages.append({"role": "system", "content": f"{self.sys_prompt}"})

        for m in historys_dto:
            messages.append(m.to_msg())

        user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, is_think_mode)
        messages.append(user_msg.to_msg())

        print(f"\n🤖 Agent [{self.name}] 思考中...\n")

        # 調用非串流方法，返回原始 response object
        response = self.brain.send_non_stream(messages, is_think_mode)
        
        # 從原始 response 提取 reasoning_content 同 content
        msg = response.choices[0].message
        reasoning_content = getattr(msg, 'reasoning_content', None) or ""
        content = msg.content or ""

        pend_save: list[MessageDTO] = []
        pend_save.append(user_msg)
        
        if reasoning_content:
            pend_save.append(
                MessageDTO.get_reasoning_msg(reasoning_content, is_think_mode)
            )
        pend_save.append(
            MessageDTO.get_assistant_msg(content, is_think_mode)
        )

        ConnPool.start_db_async_task(self._save_messages_to_db(pend_save))

        return reasoning_content, content
    
    async def _save_messages_to_db(self, messages: list[MessageDTO]):
        message_dao = MessageDAO()
        
        try:
            step_id = "step-" + str(uuid.uuid4())  # 呢一轉對話嘅 ID

            async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                for msg_dto in messages:
                    await message_dao.create(
                        session,
                        session_id=self.session_db_id,
                        step_id=step_id,
                        msg_id="msg-" + str(uuid.uuid4()),
                        msg_type=msg_dto.msg_type,
                        content=msg_dto.content,
                        is_think_mode=msg_dto.is_think_mode,
                        sent_by=msg_dto.sent_by,
                        create_date=msg_dto.date,
                        token=self._count_tokens(msg_dto.content)
                    )

                await session.commit()
            
            print(f"💾 歷史訊息已成功存入資料庫 (Agent: {self.name})")
        except Exception as e:
            print(f"❌ 儲存訊息失敗：{e}")

    def _count_tokens(self, text: str) -> int:
        """計吓段文字有幾多 Token"""
        try:
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except Exception as e:
            print(f"⚠️ Token 計算失敗：{e}")
            return 0
