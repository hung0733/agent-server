from datetime import datetime, timezone
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from uuid import UUID
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    AIMessage,
    HumanMessage,
    ToolMessage,
)

from agent.agent import Agent
from db.dao.agent_message_dao import AgentMessageDAO
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dto.collaboration_dto import AgentMessage
from db.types import MessageType
from graph.graph_node import GraphNode
from graph.graph_store import GraphStore
from graph.butler import SUMMARY_TRIGGER_TOKEN, SUMMARY_USAGE_TOKEN, workflow
from i18n import _
from ltm.simplemem import MultiAgentMemorySystem
from models.llm import LLMSet
from msg_queue.models import StreamChunk
from utils.timezone import get_server_tz, now_server, to_server_tz
from utils.tools import Tools

logger = logging.getLogger(__name__)


class Bulter(Agent):
    _graph: Any = None
    _REVIEW_MEMORY_TYPES: Tuple[str, str, str] = ("SOUL", "IDENTITY", "USER_PROFILE")

    def __init__(
        self,
        agent_db_id: str,
        session_db_id: str,
        agent_id: str,
        session_id: str,
        involves_secrets: bool,
        name: str,
    ):
        super().__init__(
            agent_db_id,
            session_db_id,
            agent_id,
            session_id,
            involves_secrets,
            name,
        )

        if Bulter._graph is None:
            if not GraphStore.checkpointer:
                logger.error(
                    _("❌ GraphStore 尚未初始化！請檢查 main.py 嘅 lifespan。")
                )
                raise RuntimeError(
                    _("GraphStore 尚未初始化！請檢查 main.py 嘅 lifespan。")
                )

            logger.debug(_("🔧 正在編譯 workflow，thread_id: %s"), self.session_id)
            Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)
            logger.debug(_("✅ Graph 編譯完成"))

        self.stm_trigger_token = SUMMARY_TRIGGER_TOKEN
        self.stm_summary_token = SUMMARY_USAGE_TOKEN

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str) -> "Bulter":
        agent_db_id, session_db_id, agent_id, session_id, involves_secrets, name = (
            await Agent.get_db_agent(agent_id, session_id)
        )

        return cls(
            agent_db_id=agent_db_id,
            session_db_id=session_db_id,
            agent_id=agent_id,
            session_id=session_id,
            involves_secrets=involves_secrets,
            name=name,
        )

    async def send(
        self,
        models: LLMSet,
        sys_prompt: str,
        message: str,
        think_mode: Optional[bool],
        metadata: Dict[str, Any],
    ) -> AsyncGenerator[StreamChunk, None]:
        logger.debug(
            _("🚀 正在發送消息到 LLM，agent: %s, session: %s"),  # type: ignore  # noqa: F823
            self.agent_id,
            self.session_id,
        )
        logger.debug(_("📝 消息長度：%s, think_mode: %s"), len(message), think_mode)  # type: ignore
        try:
            usage_payload: Optional[Dict[str, Any]] = None
            thread_id = self.session_id
            if metadata and isinstance(metadata, dict):
                thread_id_override = metadata.get("thread_id_override")
                if isinstance(thread_id_override, str) and thread_id_override.strip():
                    thread_id = thread_id_override

            # 準備 config
            config = GraphNode.prepare_chat_node_config(
                thread_id,
                models,
                sys_prompt,
                self.involves_secrets,
                think_mode,
                metadata,
            )
            # 注入 agent_db_id (自動注入到工具)
            config["configurable"]["agent_db_id"] = self.agent_db_id  # type: ignore

            async for msg, metadata in Bulter._graph.astream(
                {
                    "messages": [
                        HumanMessage(
                            content=message,
                            additional_kwargs={"datetime": datetime.now(timezone.utc)},
                        )
                    ]
                },
                config=config,
                stream_mode="messages",
            ):
                # Skip messages from Router node
                if metadata and isinstance(metadata, dict):
                    langgraph_node = metadata.get("langgraph_node", "")
                    if langgraph_node == "Router":
                        continue

                # 我哋只處理 LLM 嘔出嚟嘅 Chunk，忽略其他 LangGraph 嘅系統事件
                if isinstance(msg, AIMessageChunk):
                    chunk_usage = self._extract_provider_usage(msg, metadata)
                    if chunk_usage is not None:
                        usage_payload = chunk_usage

                    # 處理 Thinking (思考)
                    reasoning_content = msg.additional_kwargs.get("reasoning_content")
                    if reasoning_content:
                        # logger.debug(
                        #     f"🧠 收到推理內容，長度：{len(reasoning_content)}"
                        # )
                        yield StreamChunk(
                            chunk_type="think",
                            content=str(reasoning_content),
                            timestamp=time.time(),  # type: ignore
                        )

                    # 處理 Tool Calls (工具)
                    if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                        for tool_chunk in msg.tool_call_chunks:
                            # logger.debug(
                            #     f"🔧 收到工具調用：{tool_chunk.get('name')}"
                            # )
                            yield StreamChunk(
                                chunk_type="tool",
                                content=tool_chunk.get("name"),
                                data={"tool_call": tool_chunk},
                                timestamp=time.time(),  # type: ignore
                            )

                    # 處理 Content (普通對話文字)
                    if msg.content:
                        content = (
                            msg.content
                            if isinstance(msg.content, str)
                            else str(msg.content)
                        )

                        # Skip router JSON output (e.g., {"level": 1, "think": false})
                        content_stripped = content.strip()
                        if content_stripped.startswith(
                            "{"
                        ) and content_stripped.endswith("}"):
                            try:
                                import json

                                parsed = json.loads(content_stripped)
                                # Check if it's router output
                                if "level" in parsed and "think" in parsed:
                                    continue  # Skip this chunk
                            except (json.JSONDecodeError, ValueError):  # type: ignore
                                pass  # Not JSON, continue normally

                        # logger.debug(f"💬 收到內容，長度：{len(content)}")
                        yield StreamChunk(
                            chunk_type="content",
                            content=content,
                            timestamp=time.time(),  # type: ignore
                        )
                elif isinstance(msg, ToolMessage):
                    content = (
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    )
                    yield StreamChunk(
                        chunk_type="tool_result",
                        content=content,
                        timestamp=time.time(),  # type: ignore
                    )

            if usage_payload is None:
                usage_payload = await self._extract_usage_from_final_state(config)

            if usage_payload is not None:
                yield StreamChunk(
                    chunk_type="usage",
                    data={"usage": usage_payload},
                    timestamp=time.time(),  # type: ignore
                )
        except Exception as e:
            logger.error(
                _("❌ LLM 處理失敗，agentId: %s, sessionId: %s (%s): %s"),  # type: ignore
                self.agent_id,
                self.session_id,
                self.name,
                e,
                exc_info=True,
            )
            raise

        logger.debug(_("✅ LLM 串流處理完成，agent: %s"), self.agent_id)  # type: ignore

    async def _extract_usage_from_final_state(
        self, config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            state = await Bulter._graph.aget_state(config)
        except Exception:
            return None

        messages = state.values.get("messages", []) if state else []
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return self._extract_provider_usage(message)
        return None

    @staticmethod
    def _extract_provider_usage(
        msg: AIMessage | AIMessageChunk, metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        usage_metadata = getattr(msg, "usage_metadata", None)
        response_metadata = getattr(msg, "response_metadata", None) or {}

        if isinstance(usage_metadata, dict):
            input_tokens = usage_metadata.get("input_tokens")
            output_tokens = usage_metadata.get("output_tokens")
            total_tokens = usage_metadata.get("total_tokens")
        else:
            token_usage = response_metadata.get("token_usage") if isinstance(response_metadata, dict) else None
            if not isinstance(token_usage, dict):
                return None
            input_tokens = token_usage.get("prompt_tokens")
            output_tokens = token_usage.get("completion_tokens")
            total_tokens = token_usage.get("total_tokens")

        if input_tokens is None and output_tokens is None and total_tokens is None:
            return None

        provider = None
        if isinstance(metadata, dict):
            provider = metadata.get("ls_provider")

        model = response_metadata.get("model_name") if isinstance(response_metadata, dict) else None
        if model is None and isinstance(metadata, dict):
            model = metadata.get("model_name") or metadata.get("ls_model_name")

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "provider": provider,
            "model": model,
            "available": True,
        }

    async def review_stm(self, model_set: LLMSet):
        await self._proc_review_stm(Bulter._graph, model_set)

    @staticmethod
    async def review_ltm(agent_id: str) -> Dict[str, Any]:
        """Review long-term memory (LTM) for unsummarized messages.

        This method:
        1. Retrieves all unsummarized messages for the given agent
        2. Groups them by date and session_id
        3. Splits message groups if they exceed 20,000 tokens
        4. Logs the results for verification

        Args:
            agent_id: String identifier of the agent (e.g., 'agent-001')

        Returns:
            Dict with statistics about the review process
        """
        logger.info(_("🔍 開始檢視長期記憶，agent_id: %s"), agent_id)

        # Get start of today in server timezone, then convert to UTC for DB query
        now_server_tz = now_server()
        start_of_today_server = now_server_tz.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_of_today_utc = start_of_today_server.astimezone(timezone.utc)

        logger.info(
            _("📅 處理時間：%s，搵 %s 之前嘅未摘要記錄"),
            now_server_tz.isoformat(),
            start_of_today_server.isoformat(),
        )

        # Retrieve grouped messages
        grouped_messages = await AgentMessageDAO.get_unsummarized_messages_grouped(
            agent_id=agent_id,
            before_date=start_of_today_utc,
        )

        if not grouped_messages:
            logger.info(_("✅ 冇搵到未摘要嘅記錄"))
            return {"total_groups": 0, "total_messages": 0, "total_chunks": 0}

        total_messages = 0
        total_chunks = 0
        total_groups = 0

        # Cache for receiver_agent_id -> agent_name mapping (to avoid duplicate DB queries)
        from db.dao.agent_instance_dao import AgentInstanceDAO

        receiver_agent_cache: Dict[UUID, Optional[str]] = {}

        # Process each date group
        for date_str, session_groups in grouped_messages.items():
            logger.info(
                _("📆 處理日期：%s，有 %d 個 session"), date_str, len(session_groups)
            )

            # Process each session group
            for session_id, messages in session_groups.items():
                total_groups += 1
                total_messages += len(messages)

                logger.info(
                    _("🔄 處理 session: %s，共有 %d 條訊息"),
                    session_id,
                    len(messages),
                )

                # Get receiver_agent_name for this session (only once per session_id)
                receiver_agent_name: Optional[str] = None
                for msg in messages:
                    if msg.receiver_agent_id is not None:
                        # Check cache first
                        if msg.receiver_agent_id not in receiver_agent_cache:
                            # Query DB and cache result
                            receiver_agent = await AgentInstanceDAO.get_by_id(
                                msg.receiver_agent_id
                            )
                            receiver_agent_cache[msg.receiver_agent_id] = (
                                receiver_agent.name if receiver_agent else None
                            )
                            logger.debug(
                                _("🔍 查詢 receiver agent ID %s -> %s"),
                                msg.receiver_agent_id,
                                receiver_agent_cache[msg.receiver_agent_id],
                            )
                        receiver_agent_name = receiver_agent_cache[
                            msg.receiver_agent_id
                        ]
                        break  # Found receiver_agent_id for this session

                # Split messages into chunks if needed
                chunks = Bulter._split_messages_by_tokens(messages, max_tokens=20000)
                total_chunks += len(chunks)

                # Log chunk information
                for idx, chunk in enumerate(chunks, 1):
                    chunk_tokens = sum(
                        Tools.get_token_count(msg.content_json) for msg in chunk
                    )
                    logger.info(
                        _("  📦 Chunk %d/%d: %d 條訊息，共 %d tokens"),
                        idx,
                        len(chunks),
                        len(chunk),
                        chunk_tokens,
                    )

                    # Log time range of chunk
                    if chunk:
                        first_time = to_server_tz(chunk[0].created_at)
                        last_time = to_server_tz(chunk[-1].created_at)
                        logger.info(
                            _("  ⏰ 時間範圍：%s 至 %s"),
                            first_time.isoformat(),
                            last_time.isoformat(),
                        )

                        endpoints = await LLMLevelEndpointDAO.get_by_agent_instance_id(
                            agent_id=agent_id
                        )
                        await Bulter._summary_ltm(
                            agent_id,
                            session_id,
                            chunk,
                            LLMSet.from_model(endpoints),
                            receiver_agent_name,
                        )

        logger.info(
            _("✅ LTM 檢視完成：%d 個組別，%d 條訊息，分成 %d 個 chunks"),
            total_groups,
            total_messages,
            total_chunks,
        )

        return {
            "total_groups": total_groups,
            "total_messages": total_messages,
            "total_chunks": total_chunks,
            "dates_processed": list(grouped_messages.keys()),
        }

    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        return "" if text is None else text.strip()

    @staticmethod
    def _strip_json_code_fence(raw_text: str) -> str:
        content = raw_text.strip()
        if content.startswith("```") and content.endswith("```"):
            content = content.strip("`").strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
        return content

    @staticmethod
    def _build_review_msg_system_prompt() -> str:
        return """
你係記憶整理助手。你會收到：
1) 現有 memory blocks（SOUL / IDENTITY / USER_PROFILE）
2) 新訊息對話內容

任務：
- 根據新訊息，生成更新後嘅 SOUL、IDENTITY、USER_PROFILE 三段 Markdown 內容。
- 保持事實一致、避免猜測、避免重複。
- 用香港繁體中文（zh-HK）書寫。
- 只輸出一個 JSON object，格式必須完全符合指定 schema。
- 禁止輸出 markdown code fence、解釋、額外文字。

規則：
- SOUL：人格、價值觀、語氣偏好、行為準則
- IDENTITY：身份、角色、能力範圍、限制
- USER_PROFILE：使用者偏好、背景、習慣、長期需求
- 若資料不足，保留原有內容，只做必要最小改動。

輸出 Schema（必須嚴格符合）：
{
  "SOUL": {"updated_data": "string"},
  "IDENTITY": {"updated_data": "string"},
  "USER_PROFILE": {"updated_data": "string"}
}
""".strip()

    @staticmethod
    def _build_review_msg_user_message(
        messages: List[AgentMessage],
        current_memory: Dict[str, Optional[str]],
    ) -> str:
        memory_context = "\n\n".join(
            [
                f"[{memory_type}]\n{current_memory.get(memory_type) or '(empty)'}"
                for memory_type in Bulter._REVIEW_MEMORY_TYPES
            ]
        )

        dialogue_lines: List[str] = []
        for msg in messages:
            sender = "User" if msg.message_type == MessageType.request else "Assistant"
            content = msg.content_json.get("content", "") if msg.content_json else ""
            content_text = content if isinstance(content, str) else str(content)
            if not content_text.strip():
                continue
            dialogue_lines.append(f"[{msg.created_at.isoformat()}] {sender}: {content_text}")

        dialogue_text = "\n".join(dialogue_lines)

        return (
            "請根據以下資料更新三個記憶區塊。\n\n"
            "# Current Memory Blocks\n"
            f"{memory_context}\n\n"
            "# New Dialogue\n"
            f"{dialogue_text}\n"
        )

    @staticmethod
    def _parse_review_msg_output(raw_output: str) -> Dict[str, str]:
        import json

        cleaned = Bulter._strip_json_code_fence(raw_output)
        parsed = json.loads(cleaned)

        result: Dict[str, str] = {}
        for memory_type in Bulter._REVIEW_MEMORY_TYPES:
            if memory_type not in parsed:
                raise ValueError(_("分析結果缺少欄位: %s") % memory_type)
            block = parsed[memory_type]
            if not isinstance(block, dict):
                raise ValueError(_("分析結果欄位格式錯誤: %s") % memory_type)
            updated_data = block.get("updated_data")
            if not isinstance(updated_data, str):
                raise ValueError(_("updated_data 無效: %s") % memory_type)
            result[memory_type] = updated_data

        return result

    @staticmethod
    async def review_msg(agent_id: str) -> Dict[str, Any]:
        """Analyze unanalyzed messages and update SOUL/IDENTITY/USER_PROFILE."""
        from db.dao.agent_instance_dao import AgentInstanceDAO
        from db.dao.memory_block_dao import MemoryBlockDAO
        from db.dto.memory_block_dto import MemoryBlockCreate, MemoryBlockUpdate
        from msg_queue.handler import MsgQueueHandler
        from msg_queue.models import QueueTaskPriority

        logger.info(_("🔍 開始分析訊息記憶，agent_id: %s"), agent_id)

        now_server_tz = now_server()
        start_of_today_server = now_server_tz.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_of_today_utc = start_of_today_server.astimezone(timezone.utc)

        grouped_messages = await AgentMessageDAO.get_unanalyzed_messages_grouped(
            agent_id=agent_id,
            before_date=start_of_today_utc,
        )

        stats: Dict[str, Any] = {
            "total_groups": 0,
            "processed_groups": 0,
            "failed_groups": 0,
            "messages_marked_analyzed": 0,
            "changed_blocks": [],
        }

        if not grouped_messages:
            logger.info(_("✅ 冇搵到未分析訊息"))
            return stats

        agent_instance = await AgentInstanceDAO.get_by_agent_id(agent_id)
        if agent_instance is None:
            raise ValueError(_("Agent not found: %s") % agent_id)

        existing_blocks = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance.id)
        memory_by_type = {
            block.memory_type: block
            for block in existing_blocks
            if block.memory_type in Bulter._REVIEW_MEMORY_TYPES
        }

        analysis_prompt = Bulter._build_review_msg_system_prompt()

        for date_str, session_groups in grouped_messages.items():
            for session_id, messages in session_groups.items():
                stats["total_groups"] += 1

                try:
                    current_memory = {
                        memory_type: (
                            memory_by_type.get(memory_type).content
                            if memory_by_type.get(memory_type)
                            else None
                        )
                        for memory_type in Bulter._REVIEW_MEMORY_TYPES
                    }

                    user_message = Bulter._build_review_msg_user_message(
                        messages=messages,
                        current_memory=current_memory,
                    )

                    content_parts: List[str] = []
                    analysis_session_id = f"review-msg-{session_id}"
                    async for chunk in MsgQueueHandler.create_msg_queue(
                        agent_id=agent_id,
                        session_id=session_id,
                        message=user_message,
                        system_prompt=analysis_prompt,
                        think_mode=False,
                        priority=QueueTaskPriority.NORMAL,
                        metadata={
                            "source": "review_msg",
                            "review_type": "memory_analysis",
                            "thread_id_override": analysis_session_id,
                        },
                    ):
                        if chunk.chunk_type == "content" and chunk.content:
                            content_parts.append(chunk.content)

                    parsed_result = Bulter._parse_review_msg_output("".join(content_parts))

                    group_changed: List[Dict[str, Any]] = []

                    for memory_type in Bulter._REVIEW_MEMORY_TYPES:
                        updated_data = parsed_result[memory_type]
                        existing = memory_by_type.get(memory_type)
                        orig_data = existing.content if existing else None

                        if (
                            Bulter._normalize_text(orig_data)
                            == Bulter._normalize_text(updated_data)
                        ):
                            continue

                        if existing is not None:
                            updated = await MemoryBlockDAO.update(
                                MemoryBlockUpdate(
                                    id=existing.id,
                                    content=updated_data,
                                    version=existing.version + 1,
                                )
                            )
                            if updated is None:
                                raise RuntimeError(
                                    _("更新 memory block 失敗: %s") % memory_type
                                )
                            memory_by_type[memory_type] = updated
                        else:
                            created = await MemoryBlockDAO.create(
                                MemoryBlockCreate(
                                    agent_instance_id=agent_instance.id,
                                    memory_type=memory_type,
                                    content=updated_data,
                                    version=1,
                                    is_active=True,
                                )
                            )
                            memory_by_type[memory_type] = created

                        group_changed.append(
                            {
                                "memory_type": memory_type,
                                "orig_data": orig_data,
                                "updated_data": updated_data,
                            }
                        )

                    message_ids = [msg.id for msg in messages]
                    marked_count = await AgentMessageDAO.batch_update_is_analyzed(
                        message_ids=message_ids,
                        is_analyzed=True,
                    )

                    stats["messages_marked_analyzed"] += marked_count
                    stats["processed_groups"] += 1
                    stats["changed_blocks"].extend(group_changed)

                    logger.info(
                        _("✅ review_msg 完成，日期=%s session=%s changed=%d marked=%d"),
                        date_str,
                        session_id,
                        len(group_changed),
                        marked_count,
                    )

                except Exception as exc:
                    stats["failed_groups"] += 1
                    logger.error(
                        _("❌ review_msg 失敗，日期=%s session=%s error=%s"),
                        date_str,
                        session_id,
                        str(exc),
                        exc_info=True,
                    )

        return stats

    @staticmethod
    def _split_messages_by_tokens(
        messages: List[AgentMessage],
        max_tokens: int = 20000,
    ) -> List[List[AgentMessage]]:
        """Split messages into chunks based on token count.

        If a group exceeds max_tokens, split at the largest time gap between
        consecutive messages. Recursively split until all chunks are within limit.

        Args:
            messages: List of messages to split
            max_tokens: Maximum tokens per chunk (default 20,000)

        Returns:
            List of message chunks, each within the token limit
        """
        # Calculate total tokens
        total_tokens = sum(Tools.get_token_count(msg.content_json) for msg in messages)

        # If within limit, return as single chunk
        if total_tokens <= max_tokens:
            return [messages]

        # If only one message exceeds limit, can't split further
        if len(messages) == 1:
            logger.warning(
                _("⚠️  單條訊息已超過 %d tokens (%d tokens)，無法再分割"),
                max_tokens,
                total_tokens,
            )
            return [messages]

        # Find largest time gap
        max_gap_idx = Bulter._find_largest_time_gap(messages)

        # Split at the gap
        left_chunk = messages[: max_gap_idx + 1]
        right_chunk = messages[max_gap_idx + 1 :]

        # Recursively split both chunks
        left_chunks = Bulter._split_messages_by_tokens(left_chunk, max_tokens)
        right_chunks = Bulter._split_messages_by_tokens(right_chunk, max_tokens)

        return left_chunks + right_chunks

    @staticmethod
    def _find_largest_time_gap(messages: List[AgentMessage]) -> int:
        """Find the index before the largest time gap in messages.

        Args:
            messages: List of messages (must be sorted by created_at)

        Returns:
            Index i such that the gap between messages[i] and messages[i+1]
            is the largest. Returns 0 if only one message.
        """
        if len(messages) <= 1:
            return 0

        max_gap_seconds = 0
        max_gap_idx = 0

        for i in range(len(messages) - 1):
            gap = (messages[i + 1].created_at - messages[i].created_at).total_seconds()
            if gap > max_gap_seconds:
                max_gap_seconds = gap
                max_gap_idx = i

        logger.debug(
            _("🔍 最大時間差：%d 秒，位置：%d/%d"),
            int(max_gap_seconds),
            max_gap_idx + 1,
            len(messages),
        )

        return max_gap_idx

    @staticmethod
    async def _summary_ltm(
        agent_id: str,
        session_id: str,
        chunk: List[AgentMessage],
        model_set: LLMSet,
        receiver_agent_name: Optional[str] = None,
    ) -> bool:
        """Summarize messages from a chunk into long-term memory.

        This method processes a chunk of agent messages and stores them
        in the long-term memory system (SimpleMem). It:
        1. Initializes the MultiAgentMemorySystem
        2. Converts AgentMessages to Dialogues
        3. Adds dialogues to memory
        4. Finalizes the session to trigger memory building
        5. Marks all messages as summarized in the database

        Args:
            agent_id: String identifier of the agent
            session_id: String identifier of the session
            chunk: List of AgentMessage DTOs to summarize
            model_set: LLM configuration for memory system
            receiver_agent_name: Pre-fetched receiver agent name for this session

        Returns:
            True if successful, False otherwise
        """
        if not chunk:
            logger.warning(_("⚠️  收到空 chunk，跳過摘要"))
            return False

        logger.info(
            _("🔄 開始處理 LTM 摘要，agent_id: %s, session_id: %s, %d 條訊息"),
            agent_id,
            session_id,
            len(chunk),
        )

        ltm = None
        try:
            # Initialize memory system (postgres_url and qdrant_url will be read from config)
            ltm = MultiAgentMemorySystem(
                agent_id=agent_id,
                model_set=model_set,
                enable_thinking=True,
                use_streaming=False,  # Don't need streaming for batch processing
            )

            await ltm.initialize()
            logger.info(_("✅ LTM 系統初始化完成"))

            # Add all messages as dialogues
            # receiver_agent_name is pre-fetched in parent method to avoid duplicate DB queries
            dialogue_count = 0
            for msg in chunk:
                speaker = ""
                if msg.message_type in [MessageType.request]:
                    speaker = "User"
                elif msg.message_type in [MessageType.response]:
                    # Use the pre-fetched receiver agent name if available
                    speaker = (
                        receiver_agent_name if receiver_agent_name else "assistant"
                    )

                if len(speaker) > 0:
                    # Extract content from content_json
                    content = msg.content_json.get("content", "")
                    if not content:
                        # If no content, try to serialize the whole content_json
                        import json

                        content = json.dumps(msg.content_json, ensure_ascii=False)

                    # Skip empty content
                    if not content.strip():
                        continue

                    # Convert created_at to ISO 8601 string
                    timestamp = msg.created_at.isoformat()

                    # Add dialogue to memory system
                    await ltm.add_dialogue(
                        session_id=session_id,
                        speaker=speaker,
                        content=content,
                        timestamp=timestamp,
                    )
                dialogue_count += 1

            logger.info(_("✅ 已添加 %d 條對話到記憶系統"), dialogue_count)

            # Finalize session to trigger memory building
            await ltm.finalize(session_id=session_id)
            logger.info(_("✅ Session 已 finalize，記憶已建立"))

            # Batch update is_summarized in background thread
            # Use Tools.start_async_task to avoid blocking
            message_ids = [msg.id for msg in chunk]

            async def _batch_update_summarized():
                try:
                    count = await AgentMessageDAO.batch_update_is_summarized(
                        message_ids=message_ids,
                        is_summarized=True,
                    )
                    logger.info(_("✅ 已將 %d 條訊息標記為已摘要"), count)
                except Exception as e:
                    logger.error(_("❌ 批量更新 is_summarized 失敗: %s"), e, exc_info=True)

            # Start async task in background
            Tools.start_async_task(_batch_update_summarized())
            logger.debug(_("📤 已啟動批量更新任務（後台執行）"))

            return True

        except Exception as e:
            logger.error(
                _("❌ LTM 摘要處理失敗，agent_id: %s, session_id: %s: %s"),
                agent_id,
                session_id,
                e,
                exc_info=True,
            )
            return False

        finally:
            # Always close the memory system connection
            if ltm is not None:
                try:
                    await ltm.close()
                    logger.debug(_("✅ LTM 系統連接已關閉"))
                except Exception as e:
                    logger.error(_("❌ 關閉 LTM 系統連接時出錯: %s"), e)
