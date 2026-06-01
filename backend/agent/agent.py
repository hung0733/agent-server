from datetime import datetime, timezone
import logging
import time
from typing import Any, AsyncGenerator, Dict
import uuid

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from backend.dao import AgentSessionDAO
from backend.db.session import async_session_factory
from backend.graph.graph_node import GraphNode
from backend.graph.graph_store import GraphStore
from backend.graph.agent import workflow
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.llm.types import StreamChunk
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import RecallResult
from backend.utils.message import MsgUtil

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
    sender_agent_id: int | None
    sender_agent_name: str
    sender_type: str
    recv_type: str
    conversation_kind: str

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
        sender_agent_id: int | None = None,
        sender_agent_name: str | None = None,
    ):
        if sender_agent_name is None and isinstance(sender_agent_id, str):
            sender_agent_name = sender_agent_id
            sender_agent_id = None

        self.agent_db_id = agent_db_id
        self.agent_id = agent_id
        self.session_db_id = session_db_id
        self.session_id = session_id
        self.user_db_id = user_db_id
        self.user_id = user_id
        self.agent_type = agent_type
        self.recv_agent_name = recv_agent_name
        self.sender_agent_id = sender_agent_id
        self.sender_agent_name = sender_agent_name or ""
        self.sender_type = "agent" if sender_agent_id is not None else "user"
        self.recv_type = "agent"
        self.conversation_kind = (
            "agent_to_agent" if sender_agent_id is not None else "user_to_agent"
        )

        if Agent._graph is None:
            Agent._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    @classmethod
    async def get_db_agent(
        cls, agent_id: str, session_id: str
    ) -> tuple[int, int, int, str, str, str, str, str, int | None, str]:
        async with async_session_factory() as session:
            row = await AgentSessionDAO(session).get_agent_runtime_data(
                agent_id, session_id
            )

        if row is None:
            raise LookupError(t("agent.not_found") % (agent_id, session_id))

        return row

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str):
        row = await cls.get_db_agent(agent_id, session_id)
        if row[6] == "bulter":
            from backend.agent.butler import Bulter

            agent = Bulter(*row)
        else:
            agent = cls(*row)
        await agent.init_llm_models()

        return agent

    async def prepare_sys_prompt(self, mem_prompt: str):
        self.sys_prompt = mem_prompt

    async def init_llm_models(self):
        self.models = await LLMSet.from_model(self.agent_db_id)

    async def send(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        sandbox: Any | None = None,
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
            sandbox=sandbox,
            graph=Agent._graph,
        ):
            yield chunk

    @staticmethod
    async def proc_send(
        agent: "Agent",
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        sandbox: Any | None,
        graph: Any,
    ) -> AsyncGenerator[StreamChunk, None]:

        step_id: str = f"step-{uuid.uuid4()}"

        ret: RecallResult = await MemoryManager.instance().recall(
            agent_id=agent.agent_id,
            session_key=agent.session_id,
            user_text=message,
        )

        await agent.prepare_sys_prompt(
            ret.append_system_context if ret.append_system_context else ""
        )

        ltm_msg: str = ret.prepend_context if ret.prepend_context else ""

        timelines: list[BaseMessage] = MsgUtil.timelines_to_base_msg(
            ret.context_timeline
        )

        logger.debug(
            t("agent.proc_send_started"),
            step_id,
            agent.session_id,
            -len(message),
            think_mode,
        )

        config: RunnableConfig = GraphNode.prepare_chat_node_config(
            thread_id=agent.session_id,
            models=agent.models,
            sys_prompt=agent.sys_prompt,
            involves_secrets=False,
            think_mode=think_mode,
            step_id=step_id,
            args=metadata,
            sender_name=agent.sender_agent_name,
            recv_name=agent.recv_agent_name,
            sender_type=getattr(agent, "sender_type", "user"),
            recv_type=getattr(agent, "recv_type", "agent"),
            conversation_kind=getattr(agent, "conversation_kind", "user_to_agent"),
            user_db_id=agent.user_db_id,
            agent_db_id=agent.agent_db_id,
            agent_id=agent.agent_id,
            agent_type=agent.agent_type,
            sandbox=sandbox,
            ltm_msg=ltm_msg,
            timelines=timelines,
            session_db_id=agent.session_db_id,
        )

        pending_text_end = False
        previous_graph_node: str | None = None

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

            graph_node = (
                _chunk_metadata.get("langgraph_node")
                or _chunk_metadata.get("node")
                or None
            )
            if (
                pending_text_end
                and graph_node
                and previous_graph_node
                and graph_node != previous_graph_node
            ):
                pending_text_end = False
                yield StreamChunk(
                    chunk_type="text_end",
                    timestamp=time.time(),
                )
            if graph_node:
                previous_graph_node = str(graph_node)

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
                    if pending_text_end:
                        pending_text_end = False
                        yield StreamChunk(
                            chunk_type="text_end",
                            timestamp=time.time(),
                        )
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
                    if pending_text_end:
                        pending_text_end = False
                        yield StreamChunk(
                            chunk_type="text_end",
                            timestamp=time.time(),
                        )
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
                    pending_text_end = True
                    if msg.additional_kwargs.get("text_done") or isinstance(
                        msg, AIMessage
                    ) and not isinstance(msg, AIMessageChunk):
                        pending_text_end = False
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
