import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
)

from backend.graph.agent import chat_node, end_node, route_after_chat
from backend.graph.graph_node import GraphNode, MessageState
from backend.graph.interrupt_nodes import human_review_node, route_after_human_review
from backend.i18n import t
from backend.tools.bulter import assign_task

logger = logging.getLogger(__name__)


def route_after_chat_bulter(state: MessageState) -> str:
    if not state.get("messages"):
        return "end_node"

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "assign_task":
                return "pre_assign_task_node"

    tool_calls = (
        [tc.get("name") for tc in last_message.tool_calls]
        if isinstance(last_message, AIMessage) and last_message.tool_calls
        else "none"
    )
    logger.info(t("graph.bulter.assign_task.route_fallback"), tool_calls)
    return route_after_chat(state)


def pre_assign_task_node(state: MessageState, config: RunnableConfig) -> dict[str, Any]:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "assign_task":
                args = tool_call.get("args") or {}
                task_name = args.get("task_name", "?")
                goal = args.get("goal", "?")

                logger.info(
                    t("graph.bulter.assign_task.approval_requested"), task_name, goal
                )

                approval_msg = AIMessage(
                    content=t("graph.bulter.assign_task.approval_message")
                    % (task_name, goal),
                    additional_kwargs={"datetime": datetime.now(timezone.utc)},
                )
                return {
                    "messages": [approval_msg],
                    "human_review_node": "assign_task_node",
                    "human_review_data": {"task_name": task_name, "goal": goal},
                    "human_review_result": None,
                }

    return {
        "messages": [ToolMessage(content=t("graph.bulter.assign_task.invalid_call"))]
    }


async def assign_task_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:
    review_data = state.get("human_review_data") or {}
    task_name = review_data.get("task_name", "")
    goal = review_data.get("goal", "")

    result = await assign_task.coroutine(  # type: ignore
        task_name, goal, GraphNode.get_tool_runtime(state, config)
    )
    task_id = result.get("task_id") or ""
    status = result.get("status") or ""

    return {
        "messages": [
            AIMessage(
                content=t("graph.bulter.assign_task.assigned_message")
                % (task_id, task_name, status),
                additional_kwargs={"datetime": datetime.now(timezone.utc)},
            )
        ],
        "human_review_node": None,
        "human_review_data": None,
        "human_review_result": None,
    }


def route_after_pre_assign_task(state: MessageState) -> str:
    if not state.get("messages"):
        return "end_node"

    if state.get("human_review_node"):
        return "human_review_node"
    return "chat"


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("pre_assign_task_node", pre_assign_task_node)
workflow.add_node("human_review_node", human_review_node)
workflow.add_node("assign_task_node", assign_task_node)
workflow.add_node("tools", GraphNode.build_tool_node(GraphNode.get_all_tools()))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat_bulter)
workflow.add_conditional_edges("pre_assign_task_node", route_after_pre_assign_task)
workflow.add_conditional_edges("human_review_node", route_after_human_review)
workflow.add_edge("assign_task_node", "end_node")
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
