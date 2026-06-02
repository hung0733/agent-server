import logging
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.utils.message import MsgUtil
from backend.utils.tools import Tools

logger = logging.getLogger(__name__)


async def chat_node(state: MessageState, config: RunnableConfig):
    models: LLMSet = GraphNode.get_configure(config, "models")
    involves_secrets: bool = GraphNode.get_configure(config, "involves_secrets", False)
    think_mode: bool = GraphNode.get_configure(config, "think_mode", False)
    args: Dict[str, Any] = GraphNode.get_configure(config, "args", {})

    llm_endpoint_id, model_to_use = models.getModel(2, involves_secrets)
    if not model_to_use:
        raise ValueError(t("graph.agent.llm_model_missing"))

    messages: list[BaseMessage] = GraphNode.pack_message(state, config)

    logger.debug(
        t("graph.agent.chat_node_started"),
        len(messages),
        think_mode,
        bool(args),
    )
    # logger.info(messages)

    model_to_use = GraphNode.with_runtime_model_args(config, model_to_use)
    model_with_tools = GraphNode.build_tools(config, model_to_use)

    response: AIMessage = await model_with_tools.ainvoke(messages)

    GraphNode.log_base_message_response(response)
    response.additional_kwargs = {
        **response.additional_kwargs,
        "datetime": datetime.now(timezone.utc),
        "text_done": True,
    }

    Tools.start_async_task(MsgUtil.save_llm_usage(llm_endpoint_id, response))

    logger.debug(t("graph.agent.chat_node_completed"), len(str(response.content)))
    return {"messages": [response]}


async def end_node(state: MessageState, config: RunnableConfig):
    messages: list[BaseMessage] = state["messages"]

    GraphNode.store_message(config, messages)

    return


def route_after_chat(state: MessageState) -> str:
    if not state["messages"]:
        return "end_node"

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return "end_node"

    if last_message.tool_calls:
        return "tools"

    return "end_node"


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("tools", GraphNode.build_tool_node(GraphNode.get_all_tools()))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
