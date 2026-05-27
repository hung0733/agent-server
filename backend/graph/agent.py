import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
    HumanMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import (
    CompletedTurn,
    ConversationMessage,
    ToolCallMessage,
)
from backend.tools.sandbox import SandboxTools
from backend.utils.tools import Tools

logger = logging.getLogger(__name__)


async def chat_node(state: MessageState, config: RunnableConfig):
    models: LLMSet = GraphNode.get_configure(config, "models")
    involves_secrets: bool = GraphNode.get_configure(config, "involves_secrets", False)
    think_mode: bool = GraphNode.get_configure(config, "think_mode", False)
    args: Dict[str, Any] = GraphNode.get_configure(config, "args", {})

    model_to_use: Optional[ChatOpenAI] = models.getModel(2, involves_secrets)
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
    model_with_tools = _bind_tools(model_to_use, _tools_for_config(config))
    response: AIMessage = await model_with_tools.ainvoke(messages)
    GraphNode.log_base_message_response(response)
    response.additional_kwargs = {
        **response.additional_kwargs,
        "datetime": datetime.now(timezone.utc),
        "text_done": True,
    }

    logger.debug(t("graph.agent.chat_node_completed"), len(str(response.content)))
    return {"messages": [response]}


async def end_node(state: MessageState, config: RunnableConfig):
    session_id: str = GraphNode.get_configure(config, "thread_id", "")
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

    turn: CompletedTurn = CompletedTurn(
        session_key=session_id,
        user_text="",
        assistant_text="",
        messages=[],
        metadata=conversation_metadata,
    )

    message: BaseMessage
    for message in messages:
        if isinstance(message, HumanMessage):
            turn.user_text = str(message.content)
            turn.messages.append(
                ConversationMessage(
                    role="user",
                    content=str(message.content),
                    timestamp=int(
                        message.additional_kwargs["datetime"].timestamp() * 1000
                    ),
                    metadata=conversation_metadata,
                )
            )
        elif isinstance(message, AIMessage):
            if message.content:
                turn.assistant_text += str(message.content) + "\n\n"
                turn.messages.append(
                    ConversationMessage(
                        role="assistant",
                        content=str(message.content),
                        timestamp=int(
                            message.additional_kwargs["datetime"].timestamp() * 1000
                        ),
                        metadata=conversation_metadata,
                    )
                )

            if hasattr(message, "tool_calls") and len(message.tool_calls) > 0:
                for tc in getattr(message, "tool_calls", []):
                    args = tc.get("args", {})
                    tool_call_id = str(tc.get("id") or "")
                    tool_name = str(tc.get("name") or "")
                    turn.tool_call.append(
                        ToolCallMessage(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            tool_input=args,
                            tool_result="",
                            timestamp=int(
                                message.additional_kwargs["datetime"].timestamp() * 1000
                            ),
                        )
                    )

        elif isinstance(message, ToolMessage) and message.content:
            for tc in turn.tool_call:
                if tc.tool_call_id == message.tool_call_id:
                    tc.tool_result = str(message.content)

    Tools.start_async_task(
        MemoryManager.instance().capture(agent_id=agent_id, turn=turn)
    )

    return


def _tools_for_config(config: RunnableConfig) -> Sequence[Any]:
    configurable = config.get("configurable", {})
    configured_tools = configurable.get("tools")
    if configured_tools is not None:
        return configured_tools
    if configurable.get("sandbox") is not None:
        return SandboxTools
    return []


def _bind_tools(model: BaseChatModel, tools: Sequence[Any]) -> BaseChatModel:
    if not tools:
        return model

    bind_tools = getattr(model, "bind_tools", None)
    if not callable(bind_tools):
        return model

    try:
        return bind_tools(tools)
    except NotImplementedError:
        return model


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
workflow.add_node("tools", ToolNode(SandboxTools))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
