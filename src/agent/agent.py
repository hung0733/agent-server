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
                _("🧹 背景任務：Thread %s 超過 %d Token (%d)，開始壓縮記憶..."),
                self.session_id,
                self.stm_trigger_token,
                total_tokens,
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

            context = (
                ""
                if summary is not None
                else f"[本對話階段的舊有記憶 (供參考，請避免重複提取)]\n{summary}"
            )

            dialogue_text = ""
            for m in old_messages:
                # Extract timestamp if available, otherwise use empty string
                timestamp = ""
                if (
                    hasattr(m, "additional_kwargs")
                    and "timestamp" in m.additional_kwargs
                ):
                    timestamp = f"[{m.additional_kwargs['timestamp']}] "
                elif hasattr(m, "created_at") and m.created_at:
                    timestamp = f"[{m.created_at}] "

                # Use message name/sender if available, otherwise use role
                sender = ""
                if hasattr(m, "name") and m.name:
                    sender = m.name
                else:
                    sender = "User" if m.type == "human" else "AI"

                content_str = (
                    m.content if isinstance(m.content, str) else str(m.content)
                )
                dialogue_text += f"{timestamp}{sender}: {content_str}\n"

            prompt = f"""
你是一位專業的資訊提取助理，擅長從對話中提取結構化、無歧義的資訊。

你的任務是從以下對話中提取所有有價值的資訊，並將其轉化為結構化的記憶條目 (Memory Entries)。

{context}

[當前視窗的最新對話紀錄]
{dialogue_text}

[核心要求]
1. **全面覆蓋 (Complete Coverage)**：產生足夠數量的記憶條目，確保對話中的「所有」關鍵資訊及細節均被妥善捕捉。
2. **強制消除歧義 (Force Disambiguation)**：絕對禁止使用代名詞 (例如：他、她、它、他們、這個、那個) 以及相對時間 (例如：昨日、今日、上星期、明日)。必須替換為具體人名、確實事物名稱或絕對時間 (Timestamp)。
3. **無損資訊 (Lossless Information)**：每一條記憶的重述必須是一個完整、獨立且語意清晰的句子。確保該句子即使完全脫離上下文，也能被獨立理解。

[輸出格式]
只允許輸出點列式字串 (Point Form String Only)，每一項代表一條記憶條目：
- 無損重述的完整句子
- 無損重述的完整句子
- 無損重述的完整句子

[範例參考]
對話紀錄：
[2025-11-15T14:30:00] Alice: Bob，聽日下晝兩點我哋喺 Starbucks 見面，傾下個新 product 啦。
[2025-11-15T14:31:00] Bob: OK，我會準備好啲資料。

輸出：
- Alice 於 2025-11-15T14:30:00 提議與 Bob 在 2025-11-16T14:00:00 於 Starbucks 會面討論新產品。
- Bob 同意出席與 Alice 的會面，並承諾會準備相關討論資料。

現在請處理上述的 [當前視窗的最新對話紀錄]。嚴格遵守點列式輸出，嚴禁包含任何開場白、結語或其他解釋。
"""

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

                        logger.debug(_("🤖 背景任務：正在呼叫 LLM 進行總結..."))
                        summary_response = await model.ainvoke(
                            [HumanMessage(content=prompt)]
                        )

                        # 💡 神奇魔法：使用 aupdate_state 直接由外部改寫 DB！
                        delete_msgs = [RemoveMessage(id=m.id) for m in old_messages]

                        logger.debug(
                            _("🗑️ 背景任務：正在從 Checkpoint 刪除 %d 條舊訊息..."),
                            len(delete_msgs),
                        )

                        if not summary.endswith("\n"):
                            summary += "\n"

                        await graph.aupdate_state(
                            config,
                            {
                                "summary": summary + summary_response.content,
                                "messages": delete_msgs,
                            },
                        )
                        logger.info(_("✅ 背景任務：記憶壓縮完成！"))
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
            logger.error(_("❌ 背景壓縮記憶失敗：%s"), e)
