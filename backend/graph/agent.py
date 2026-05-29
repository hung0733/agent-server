import logging
from datetime import datetime, timezone
from typing import Any, Dict, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
    HumanMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.dto.agent_msg_hist import AgentMsgHistCreate
from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import (
    CompletedTurn,
    ConversationMessage,
    ToolCallMessage,
)
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
    session_id: str = GraphNode.get_configure(config, "thread_id", "")
    session_db_id: int = GraphNode.get_configure(config, "session_db_id", 0)
    step_id: str = GraphNode.get_configure(config, "step_id", "")
    agent_id: str = GraphNode.get_configure(config, "agent_id", "")
    conversation_metadata = {
        "conversation_kind": GraphNode.get_configure(
            config, "conversation_kind", "unknown"
        ),
        "sender_name": GraphNode.get_configure(config, "sender_name", ""),
        "sender_type": GraphNode.get_configure(config, "sender_type", "unknown"),
        "recv_name": GraphNode.get_configure(config, "recv_name", ""),
        "recv_type": GraphNode.get_configure(config, "recv_type", "agent"),
    }
    messages: list[BaseMessage] = state["messages"]
    # logger.info(messages)

    user_msg, assistant_msg, cm, tcm = MsgUtil.base_msg_to_tdai_memory_rec(
        messages, conversation_metadata
    )

    dtos: list[AgentMsgHistCreate] = MsgUtil.base_msg_to_msg_hist_rec(
        messages, session_db_id, step_id, conversation_metadata
    )

    turn: CompletedTurn = CompletedTurn(
        session_key=session_id,
        user_text=user_msg,
        assistant_text=assistant_msg,
        messages=cm,
        tool_call=tcm,
        metadata=conversation_metadata,
    )

    Tools.start_async_task(
        MemoryManager.instance().capture(agent_id=agent_id, turn=turn)
    )

    Tools.start_async_task(MsgUtil.save_agent_msg_hist(dtos))

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
workflow.add_node("tools", ToolNode(GraphNode.get_all_tools()))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
