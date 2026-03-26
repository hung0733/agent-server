from datetime import datetime
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    AIMessage,
    HumanMessage,
    ToolMessage,
)

from agent.agent import Agent
from graph.graph_node import GraphNode
from graph.graph_store import GraphStore
from graph.butler import SUMMARY_TRIGGER_TOKEN, SUMMARY_USAGE_TOKEN, workflow
from i18n import _
from models.llm import LLMSet
from msg_queue.models import StreamChunk

logger = logging.getLogger(__name__)


class Bulter(Agent):
    _graph: Any = None

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
            # 準備 config
            config = GraphNode.prepare_chat_node_config(
                self.session_id,
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
                            additional_kwargs={"datetime": datetime.now()},
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
        except Exception as e:
            logger.error(
                _("❌ LLM 處理失敗，agentId: %s, sessionId: %s (%s): %s"),  # type: ignore
                self.agent_id,
                self.session_id,
                self.name,
                e,
            )
            raise

        logger.debug(_("✅ LLM 串流處理完成，agent: %s"), self.agent_id)  # type: ignore

    async def review_stm(self, model_set: LLMSet):
        await self._proc_review_stm(Bulter._graph, model_set)
