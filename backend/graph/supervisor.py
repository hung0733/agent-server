import json
import logging
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.dao import AgentDAO
from backend.db.session import async_session_factory
from backend.graph.agent import chat_node, end_node
from backend.graph.graph_node import MessageState
from backend.tools.sandbox import SandboxTools
from backend.tools.system import assign_task

logger = logging.getLogger(__name__)

ASSIGN_TASK_MAX_RETRIES = 2


async def chat_node_with_assign_task(state: MessageState, config: RunnableConfig):
    configurable = config.get("configurable", {})
    tools = (
        [assign_task, *SandboxTools]
        if configurable.get("sandbox")
        else [assign_task]
    )
    return await chat_node(
        state,
        {
            **config,
            "configurable": {
                **configurable,
                "tools": tools,
            },
        },
    )


async def assign_task_node(state: MessageState, config: RunnableConfig):
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return {"messages": []}

    tool_messages: list[ToolMessage] = []
    allowed_agent_names = await _get_allowed_agent_names(config)
    assign_task_config = _with_allowed_agent_names(config, allowed_agent_names)
    for tool_call in last_message.tool_calls:
        if tool_call.get("name") != "assign_task":
            continue

        tool_call_id = str(tool_call.get("id") or "")
        runtime = ToolRuntime(
            state=state,
            context=None,
            config=assign_task_config,
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


def route_after_assign_task(state: MessageState) -> str:
    if not _last_assign_task_rejected(state):
        return "end_node"
    if _assign_task_rejection_count(state) <= ASSIGN_TASK_MAX_RETRIES:
        return "chat"
    return "end_node"


async def _get_allowed_agent_names(config: RunnableConfig) -> list[str]:
    configurable = config.get("configurable", {})
    configured_names = configurable.get("assign_task_allowed_agent_names")
    if isinstance(configured_names, list):
        return [
            name for name in configured_names if isinstance(name, str) and name.strip()
        ]

    user_db_id = configurable.get("user_db_id")
    if user_db_id is None:
        return []

    async with async_session_factory() as session:
        agents = await AgentDAO(session).list_by_user_id(int(user_db_id))

    return [agent.name for agent in agents if agent.is_active]


def _with_allowed_agent_names(
    config: RunnableConfig, allowed_agent_names: list[str]
) -> RunnableConfig:
    return {
        **config,
        "configurable": {
            **config.get("configurable", {}),
            "assign_task_allowed_agent_names": allowed_agent_names,
        },
    }


def _last_assign_task_rejected(state: MessageState) -> bool:
    if not state["messages"]:
        return False
    last_message = state["messages"][-1]
    if not isinstance(last_message, ToolMessage):
        return False
    payload = _tool_message_json(last_message)
    return payload.get("accepted") is False


def _assign_task_rejection_count(state: MessageState) -> int:
    count = 0
    for message in state["messages"]:
        if not isinstance(message, ToolMessage):
            continue
        payload = _tool_message_json(message)
        if payload.get("accepted") is False:
            count += 1
    return count


def _tool_message_json(message: ToolMessage) -> dict[str, Any]:
    content = (
        message.content if isinstance(message.content, str) else str(message.content)
    )
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def route_after_chat(state: MessageState) -> str:
    if not state["messages"]:
        return "end_node"

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return "end_node"

    for tool_call in last_message.tool_calls:
        if tool_call.get("name") == "assign_task":
            return "assign_task"

    if last_message.tool_calls:
        return "tools"

    return "end_node"


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node_with_assign_task)
workflow.add_node("assign_task", assign_task_node)
workflow.add_node("tools", ToolNode(SandboxTools))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_conditional_edges("assign_task", route_after_assign_task)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
