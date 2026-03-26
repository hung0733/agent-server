import logging
from typing import Any, List

from langchain.messages import RemoveMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from db.crypto import CryptoManager
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from db.dto.memory_block_dto import MemoryBlock
from i18n import _
from models.llm import LLMSet
from utils.tools import Tools

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

    async def _proc_review_stm(self, graph: Any, model_set: LLMSet):
        try:
            config = {"configurable": {"thread_id": self.session_id}}
            state = await graph.aget_state(config)

            if not state or not state.values:
                return

            messages = state.values.get("messages", [])
            summary = state.values.get("summary", "")

            total_tokens = sum(Tools.get_token_count(m.content) for m in messages)

            # 如果未爆 Token，直接收工，乜都唔使做
            if total_tokens <= self.stm_trigger_token:
                return

            logger.info(
                f"🧹 背景任務：Thread {self.session_id} 超過 {self.stm_trigger_token} Token ({total_tokens})，開始壓縮記憶..."
            )

            # 尋找切割點
            tokens = 0
            split_idx = 0
            for i, m in enumerate(messages):
                tokens += Tools.get_token_count(m.content)
                if tokens >= self.stm_summary_token:
                    split_idx = i + 1
                    # 確保一整輪對話完整性
                    while (
                        split_idx < len(messages)
                        and messages[split_idx].type != "human"
                    ):
                        split_idx += 1
                    break

            if split_idx == 0 or split_idx >= len(messages):
                split_idx = max(1, len(messages) // 2)

            old_messages = messages[:split_idx]

            prompt = "請根據以下對話記錄，總結出一個精簡的摘要。保留重要資訊、用戶偏好及已確認的決定。"
            if summary:
                prompt += f"\n\n【現有舊摘要】\n{summary}"
            prompt += "\n\n【需總結的新對話】\n"
            for m in old_messages:
                role = "User" if m.type == "human" else "AI"
                content_str = (
                    m.content if isinstance(m.content, str) else str(m.content)
                )
                prompt += f"{role}: {content_str}\n"

            for level in range(2, 0, -1):
                models = model_set.level[level]
                for model_dto in models:
                    try:
                        # Handle API key - use placeholder for local models without auth
                        if model_dto.api_key_encrypted:
                            api_key = CryptoManager().decrypt(
                                model_dto.api_key_encrypted
                            )
                        else:
                            api_key = "EMPTY"  # Placeholder for local models

                        model: BaseChatModel = ChatOpenAI(
                            base_url=model_dto.base_url,
                            api_key=SecretStr(api_key),
                            model=model_dto.model_name,
                            streaming=True,
                        )

                        model = model.bind(
                            temperature=0.3,
                            extra_body={
                                "chat_template_kwargs": {"enable_thinking": True},
                            },
                        )  # type: ignore

                        logger.debug("🤖 背景任務：正在呼叫 LLM 進行總結...")
                        summary_response = await model.ainvoke(
                            [HumanMessage(content=prompt)]
                        )

                        # 💡 神奇魔法：使用 aupdate_state 直接由外部改寫 DB！
                        delete_msgs = [RemoveMessage(id=m.id) for m in old_messages]

                        logger.debug(
                            f"🗑️ 背景任務：正在從 Checkpoint 刪除 {len(delete_msgs)} 條舊訊息..."
                        )
                        await graph.aupdate_state(
                            config,
                            {
                                "summary": summary_response.content,
                                "messages": delete_msgs,
                            },
                        )
                        logger.info("✅ 背景任務：記憶壓縮完成！")
                        Tools.start_async_task(
                            LLMEndpointDAO.record_feedback(model_dto.id, success=True)
                        )

                        pass
                    except Exception as exc:
                        # Handle Fail Model
                        logger.error(
                            _(" 模型 %s 呼叫失敗: %s"),
                            model_dto.model_name,
                            exc,
                            exc_info=True,
                        )
                        Tools.start_async_task(
                            LLMEndpointDAO.record_feedback(model_dto.id, success=False)
                        )
        except Exception as e:
            logger.error(f"❌ 背景壓縮記憶失敗：{e}")
