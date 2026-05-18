import logging
from typing import Any, Dict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.graph.graph_node import MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.llm.types import StreamChunk

logger = logging.getLogger(__name__)


async def chat_node(state: MessageState, config: RunnableConfig):
    models: LLMSet = config["configurable"]["models"]  # type: ignore
    sys_prompt: str = config["configurable"]["sys_prompt"] or ""  # type: ignore
    think_mode: bool = config["configurable"]["think_mode"] or False  # type: ignore
    args: Dict[str, Any] = config["configurable"]["args"] or {}  # type: ignore

    model_to_use = models.getSysActModel()
    if not model_to_use:
        raise ValueError(t("graph.agent.llm_model_missing"))

    last_message: BaseMessage = state["messages"][-1]
    messages: list[BaseMessage] = [last_message]
    if sys_prompt:
        messages.insert(0, SystemMessage(content=sys_prompt))

    logger.debug(
        t("graph.agent.chat_node_started"),
        len(messages),
        think_mode,
        bool(args),
    )
    response = await model_to_use.ainvoke(messages)

    if isinstance(response, BaseMessage):
        _log_base_message_response(response)
        ai_message = response
    else:
        content_parts: list[str] = []
        for chunk in response:
            if not isinstance(chunk, StreamChunk):
                continue
            _log_stream_chunk_response(chunk)
            if chunk.chunk_type == "content" and chunk.content:
                content_parts.append(chunk.content)

        content = "".join(content_parts)
        if not content:
            raise ValueError(t("graph.agent.empty_llm_response"))
        ai_message = AIMessage(content=content)

    logger.debug(t("graph.agent.chat_node_completed"), len(str(ai_message.content)))
    return {"messages": [ai_message]}


def _log_stream_chunk_response(chunk: StreamChunk) -> None:
    if chunk.chunk_type == "content":
        logger.info(
            t("graph.agent.chat_node_content_chunk_received"),
            len(chunk.content or ""),
        )
    elif chunk.chunk_type == "tool":
        logger.info(
            t("graph.agent.chat_node_tool_chunk_received"),
            chunk.content or _tool_name_from_chunk(chunk),
        )
    elif chunk.chunk_type == "tool_result":
        logger.info(
            t("graph.agent.chat_node_tool_result_chunk_received"),
            len(chunk.content or ""),
        )


def _log_base_message_response(message: BaseMessage) -> None:
    content = message.content if isinstance(message.content, str) else str(message.content)
    if content:
        logger.info(t("graph.agent.chat_node_content_chunk_received"), len(content))

    for tool_call in getattr(message, "tool_calls", []) or []:
        logger.info(
            t("graph.agent.chat_node_tool_chunk_received"),
            tool_call.get("name", ""),
        )


def _tool_name_from_chunk(chunk: StreamChunk) -> str:
    data = chunk.data or {}
    tool_call = data.get("tool_call")
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "")
    return ""


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)

workflow.add_edge(START, "chat")
workflow.add_edge("chat", END)

graph = workflow.compile()
