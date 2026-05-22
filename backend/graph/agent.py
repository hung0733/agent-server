import json
import logging
from typing import Any, Dict, Optional, Sequence

from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.tools.sandbox import SandboxTools
from backend.tools.system import SystemTools, assign_task

logger = logging.getLogger(__name__)

AgentTools = [*SystemTools, *SandboxTools]


async def chat_node(state: MessageState, config: RunnableConfig):
    models: LLMSet = config["configurable"]["models"]  # type: ignore
    sys_prompt: str = config["configurable"]["sys_prompt"] or ""  # type: ignore
    involves_secrets: bool = config["configurable"]["involves_secrets"] or False  # type: ignore
    think_mode: bool = config["configurable"]["think_mode"] or False  # type: ignore
    args: Dict[str, Any] = config["configurable"]["args"] or {}  # type: ignore

    model_to_use: Optional[BaseChatModel] = models.getModel(2, involves_secrets)
    if not model_to_use:
        raise ValueError(t("graph.agent.llm_model_missing"))

    messages: list[BaseMessage] = list(state["messages"])
    if sys_prompt:
        messages.insert(0, SystemMessage(content=sys_prompt))

    logger.debug(
        t("graph.agent.chat_node_started"),
        len(messages),
        think_mode,
        bool(args),
    )

    model_with_tools = _bind_tools(model_to_use, _tools_for_config(config))
    response: AIMessage = await model_with_tools.ainvoke(messages)
    GraphNode.log_base_message_response(response)
    response.additional_kwargs = {
        **response.additional_kwargs,
        "text_done": True,
    }

    logger.debug(t("graph.agent.chat_node_completed"), len(str(response.content)))
    return {"messages": [response]}


def _tools_for_config(config: RunnableConfig) -> Sequence[Any]:
    configurable = config.get("configurable", {})
    if configurable.get("sandbox") is not None:
        return AgentTools
    return SystemTools


def _bind_tools(model: BaseChatModel, tools: Sequence[Any]) -> BaseChatModel:
    bind_tools = getattr(model, "bind_tools", None)
    if not callable(bind_tools):
        return model

    try:
        return bind_tools(tools)
    except NotImplementedError:
        return model


def route_after_chat(state: MessageState) -> str:
    if not state["messages"]:
        return END

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return END

    for tool_call in last_message.tool_calls:
        if tool_call.get("name") == "assign_task":
            return "assign_task"

    if last_message.tool_calls:
        return "tools"

    return END


async def assign_task_node(state: MessageState, config: RunnableConfig):
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return {"messages": []}

    tool_messages: list[ToolMessage] = []
    for tool_call in last_message.tool_calls:
        if tool_call.get("name") != "assign_task":
            continue

        tool_call_id = str(tool_call.get("id") or "")
        runtime = ToolRuntime(
            state=state,
            context=None,
            config=config,
            stream_writer=lambda _: None,
            tool_call_id=tool_call_id,
            store=None,
        )
        result = assign_task.func(
            tool_call.get("args", {}).get("task_json", ""),
            runtime,
        )
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call_id,
            )
        )

    return {"messages": tool_messages}


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("assign_task", assign_task_node)
workflow.add_node("tools", ToolNode(SandboxTools))

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_edge("assign_task", END)
workflow.add_edge("tools", "chat")

graph = workflow.compile()
