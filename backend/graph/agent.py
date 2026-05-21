import logging
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.llm.types import StreamChunk

logger = logging.getLogger(__name__)


async def chat_node(state: MessageState, config: RunnableConfig):
    models: LLMSet = config["configurable"]["models"]  # type: ignore
    sys_prompt: str = config["configurable"]["sys_prompt"] or ""  # type: ignore
    involves_secrets: bool = config["configurable"]["involves_secrets"] or False  # type: ignore
    think_mode: bool = config["configurable"]["think_mode"] or False  # type: ignore
    args: Dict[str, Any] = config["configurable"]["args"] or {}  # type: ignore

    model_to_use: Optional[BaseChatModel] = models.getModel(2, involves_secrets)
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
    if isinstance(response, list) and all(isinstance(chunk, StreamChunk) for chunk in response):
        for chunk in response:
            GraphNode.log_stream_chunk_response(chunk)
        response = GraphNode.stream_chunks_to_message(response)
    else:
        GraphNode.log_base_message_response(response)

    if isinstance(response, AIMessage):
        response.additional_kwargs = {
            **response.additional_kwargs,
            "text_done": True,
        }

    logger.debug(t("graph.agent.chat_node_completed"), len(str(response.content)))
    return {"messages": [response]}


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)

workflow.add_edge(START, "chat")
workflow.add_edge("chat", END)

graph = workflow.compile()
