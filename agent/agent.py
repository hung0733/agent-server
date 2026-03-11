from typing import AsyncGenerator, Optional, Tuple
import uuid

import tiktoken

from db.agent_dao import AgentDAO
from db.conn_pool import ConnPool
from db.message_dao import MessageDAO
from db.session_dao import SessionDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.session import SessionDTO
from global_var import GlobalVar


class Agent:
    def __init__(
        self,
        db_id: int,
        agent_id: str,
        session_db_id: int,
        session_id: str,
        name: str,
        sys_prompt: str,
        stream: bool,
    ):
        self.db_id = db_id
        self.agent_id = agent_id
        self.session_db_id = session_db_id
        self.session_id = session_id
        self.name = name
        self.sys_prompt = (sys_prompt,)
        self.stream = stream

    @staticmethod
    async def get_db_agent(
        agent_id: str, session_id: str = "default"
    ) -> tuple[Optional[AgentDTO], Optional[SessionDTO]]:
        """
        喺 DB 攞資料並初始化 Agent (使用 DAO)
        """
        agent_dao = AgentDAO()
        session_dao = SessionDAO()

        agent_dto: Optional[AgentDTO] = None
        session_dto: Optional[SessionDTO] = None

        # 喺 DB 搵對應嘅 agent_id 同 session
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            db_agent = await agent_dao.get_by_agent_id(session, agent_id)

            if not db_agent:
                print(f"⚠️ Agent {agent_id} 唔存在喺資料庫。")
                return (agent_dto, session_dto)

            # 根據 session_id 獲取 Session (default 需要配合 agent_db_id，其他可以單獨查找)
            if session_id == "default":
                db_session = await session_dao.get_default_session(session, db_agent.id)
            else:
                db_session = await session_dao.get_by_session_id(session, session_id)

            if not db_session:
                print(f"⚠️ Session {session_id} 唔存在喺資料庫。")
                return (agent_dto, session_dto)

        return (AgentDTO.from_model(db_agent), SessionDTO.from_model(db_session))

    @staticmethod
    async def handleMsgResponse(
        agent: "Agent",
        is_think_mode: bool,
        sendMsg: MessageDTO,
        response: Tuple[str, str],
    ) -> Tuple[str, str]:
        msg = response.choices[0].message
        reasoning_content = getattr(msg, "reasoning_content", None) or ""
        content = msg.content or ""

        messages: list[MessageDTO] = [sendMsg]
        if reasoning_content:
            messages.append(
                MessageDTO.get_reasoning_msg(reasoning_content, is_think_mode)
            )

        messages.append(MessageDTO.get_assistant_msg(content, is_think_mode))

        ConnPool.start_db_async_task(Agent._save_messages_to_db(agent, messages))

        return reasoning_content, content

    @staticmethod
    async def handleAsyncGenerator(
        agent: "Agent", is_think_mode: bool, sendMsg: MessageDTO, gen: AsyncGenerator
    ):
        full_reasoning = ""
        full_content = ""

        # 使用 async for 遍歷 raw_response_gen（因為它已經是 async generator）
        async for chunk in gen:
            yield chunk

            # 收集 content 同 reasoning 用於保存
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta

                # 提取 reasoning_content
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    full_reasoning += reasoning

                # 提取 content
                if delta.content:
                    full_content += delta.content

        messages: list[MessageDTO] = [sendMsg]
        if full_reasoning:
            messages.append(MessageDTO.get_reasoning_msg(full_reasoning, is_think_mode))

        messages.append(MessageDTO.get_assistant_msg(full_content, is_think_mode))

        ConnPool.start_db_async_task(Agent._save_messages_to_db(agent, messages))

    @staticmethod
    async def _save_messages_to_db(agent: "Agent", messages: list[MessageDTO]):
        message_dao = MessageDAO()

        try:
            step_id = "step-" + str(uuid.uuid4())  # 呢一轉對話嘅 ID

            async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                for msg_dto in messages:
                    await message_dao.create(
                        session,
                        session_id=agent.session_db_id,
                        step_id=step_id,
                        msg_id="msg-" + str(uuid.uuid4()),
                        msg_type=msg_dto.msg_type,
                        content=msg_dto.content,
                        is_think_mode=msg_dto.is_think_mode,
                        sent_by=msg_dto.sent_by,
                        create_date=msg_dto.date,
                        token=Agent._count_tokens(msg_dto.content),
                    )

                await session.commit()

            print(f"💾 歷史訊息已成功存入資料庫 (Agent: {agent.name})")
        except Exception as e:
            print(f"❌ 儲存訊息失敗：{e}")

    @staticmethod
    def _count_tokens(text: str) -> int:
        """計吓段文字有幾多 Token"""
        try:
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except Exception as e:
            print(f"⚠️ Token 計算失敗：{e}")
            return 0
