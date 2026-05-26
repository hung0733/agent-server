from datetime import datetime, timezone
import logging
import time
from typing import Any, AsyncGenerator, Dict
import uuid

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from backend.dao import AgentSessionDAO
from backend.db.session import async_session_factory
from backend.dto.agent import SUMMARY_TRIGGER_TOKEN, SUMMARY_USAGE_TOKEN
from backend.graph.graph_node import GraphNode
from backend.graph.graph_store import GraphStore
from backend.graph.agent import workflow
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.llm.types import StreamChunk
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import RecallResult

logger = logging.getLogger(__name__)


class Agent:
    _graph: Any = None

    user_db_id: int
    agent_db_id: int
    session_db_id: int

    user_id: str
    agent_id: str
    session_id: str

    agent_type: str

    recv_agent_name: str
    sender_agent_name: str

    stm_trigger_token: int
    stm_summary_token: int

    models: LLMSet

    def __init__(
        self,
        user_db_id: int,
        agent_db_id: int,
        session_db_id: int,
        user_id: str,
        agent_id: str,
        session_id: str,
        agent_type: str,
        recv_agent_name: str,
        sender_agent_name: str,
    ):
        self.agent_db_id = agent_db_id
        self.agent_id = agent_id
        self.session_db_id = session_db_id
        self.session_id = session_id
        self.user_db_id = user_db_id
        self.user_id = user_id
        self.agent_type = agent_type
        self.recv_agent_name = recv_agent_name
        self.sender_agent_name = sender_agent_name

        self.stm_trigger_token = SUMMARY_TRIGGER_TOKEN
        self.stm_summary_token = SUMMARY_USAGE_TOKEN

        if Agent._graph is None:
            Agent._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    @classmethod
    async def get_db_agent(
        cls, agent_id: str, session_id: str
    ) -> tuple[int, int, int, str, str, str, str, str, str]:
        async with async_session_factory() as session:
            row = await AgentSessionDAO(session).get_agent_runtime_data(
                agent_id, session_id
            )

        if row is None:
            raise LookupError(t("agent.not_found") % (agent_id, session_id))

        return row

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str):
        agent = cls(*(await cls.get_db_agent(agent_id, session_id)))
        await agent.init_llm_models()

        return agent

    async def prepare_sys_prompt(self):
        self.sys_prompt = ""

    async def init_llm_models(self):
        self.models = await LLMSet.from_model(self.agent_db_id)

    async def send(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
    ) -> AsyncGenerator[StreamChunk, None]:
        logger.info(
            t("agent.send_started"),
            self.session_id,
            len(message),
            think_mode,
        )
        async for chunk in Agent.proc_send(
            agent=self,
            message=message,
            think_mode=think_mode,
            metadata=metadata,
            graph=Agent._graph,
        ):
            yield chunk

    @staticmethod
    async def proc_send(
        agent: "Agent",
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        graph: Any,
    ) -> AsyncGenerator[StreamChunk, None]:

        step_id: str = f"step-{uuid.uuid4()}"

        ret: RecallResult = await MemoryManager.instance().recall(
            agent_id=agent.agent_id,
            session_key=agent.session_id,
            user_text=message,
        )

        sys_prompt: str = ""
        if ret.append_system_context:
            sys_prompt = ret.append_system_context

        if ret.prepend_context:
            logger.info("Recall L1 Memory: " + ret.prepend_context)

        logger.debug(
            t("agent.proc_send_started"),
            step_id,
            agent.session_id,
            len(message),
            think_mode,
        )

        config: RunnableConfig = GraphNode.prepare_chat_node_config(
            thread_id=agent.session_id,
            models=agent.models,
            sys_prompt=sys_prompt,
            involves_secrets=False,
            think_mode=think_mode,
            step_id=step_id,
            args=metadata,
            sender_name=agent.sender_agent_name,
            recv_name=agent.recv_agent_name,
            stm_trigger_token=agent.stm_trigger_token,
            stm_summary_token=agent.stm_summary_token,
            user_db_id=agent.user_db_id,
            agent_id=agent.agent_id,
        )

        async for chunk in graph.astream(
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
            if isinstance(chunk, tuple):
                msg, _chunk_metadata = chunk
            else:
                msg = chunk
                _chunk_metadata = {}

            if isinstance(msg, (AIMessage, AIMessageChunk)):
                reasoning_content = msg.additional_kwargs.get("reasoning_content")
                if reasoning_content:
                    logger.debug(
                        t("agent.chunk_received"),
                        step_id,
                        agent.session_id,
                        "think",
                        len(str(reasoning_content)),
                    )
                    yield StreamChunk(
                        chunk_type="think",
                        content=str(reasoning_content),
                        timestamp=time.time(),
                    )

                if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:  # type: ignore
                    for tool_chunk in msg.tool_call_chunks:  # type: ignore
                        logger.debug(
                            t("agent.tool_call_received"),
                            step_id,
                            agent.session_id,
                            tool_chunk.get("name"),
                        )
                        yield StreamChunk(
                            chunk_type="tool",
                            content=tool_chunk.get("name"),
                            data={"tool_call": tool_chunk},
                            timestamp=time.time(),
                        )
                elif hasattr(msg, "tool_calls") and msg.tool_calls:  # type: ignore
                    for tc in getattr(msg, "tool_calls", []):
                        logger.debug(
                            t("agent.tool_call_received"),
                            step_id,
                            agent.session_id,
                            tc.get("name"),
                        )
                        yield StreamChunk(
                            chunk_type="tool",
                            content=tc.get("name"),
                            data={"tool_call": tc},
                            timestamp=time.time(),
                        )

                if msg.content:
                    content = (
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    )
                    logger.debug(
                        t("agent.chunk_received"),
                        step_id,
                        agent.session_id,
                        "content",
                        len(content),
                    )
                    yield StreamChunk(
                        chunk_type="content",
                        content=content,
                        timestamp=time.time(),
                    )
                    if msg.additional_kwargs.get("text_done"):
                        yield StreamChunk(
                            chunk_type="text_end",
                            timestamp=time.time(),
                        )
            elif isinstance(msg, ToolMessage):
                content = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
                logger.debug(
                    t("agent.chunk_received"),
                    step_id,
                    agent.session_id,
                    "tool_result",
                    len(content),
                )
                yield StreamChunk(
                    chunk_type="tool_result",
                    content=content,
                    timestamp=time.time(),
                )

        logger.debug(t("agent.proc_send_completed"), step_id, agent.session_id)
