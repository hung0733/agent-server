import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolRuntime
from langgraph.graph import END, START, StateGraph

from backend.graph.agent import chat_node, end_node, route_after_chat
from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.tools.memory import MemoryTools
from backend.tools.sandbox import SandboxTools
from backend.tools.system import SystemTools, assign_task

logger = logging.getLogger(__name__)

ASSIGN_TASK_APPROVE_ID = "assign_task_approve"
ASSIGN_TASK_CANCEL_ID = "assign_task_cancel"


async def approval_gate_node(state: MessageState, config: RunnableConfig):
    return {}


def route_after_approval_gate(state: MessageState) -> str:
    pending = state.get("pending_assign_task")
    if pending and state.get("messages"):
        last_message = state["messages"][-1]
        if isinstance(last_message, HumanMessage):
            content = str(last_message.content).strip().lower()
            if content in {ASSIGN_TASK_APPROVE_ID, ASSIGN_TASK_CANCEL_ID}:
                return "assign_task_approval_response"
    return "chat"


def route_after_butler_chat(state: MessageState) -> str:
    if not state.get("messages"):
        return "end_node"

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "assign_task":
                return "assign_task_approval_request"

    return route_after_chat(state)


async def assign_task_approval_request_node(
    state: MessageState, config: RunnableConfig
):
    last_message = state["messages"][-1]
    task_args: dict[str, Any] = {}
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "assign_task":
                args = tool_call.get("args")
                if isinstance(args, dict):
                    task_args = args
                break

    pending = {
        "task_name": str(task_args.get("task_name") or "").strip(),
        "goal": str(task_args.get("goal") or "").strip(),
    }
    content = t("graph.bulter.assign_task.approval_request") % (
        pending["task_name"],
        pending["goal"],
    )
    return {
        "pending_assign_task": pending,
        "messages": [
            AIMessage(
                content=content,
                additional_kwargs={
                    "interactive_buttons": [
                        {
                            "id": ASSIGN_TASK_APPROVE_ID,
                            "type": "reply",
                            "displayText": t(
                                "graph.bulter.assign_task.approve_button"
                            ),
                        },
                        {
                            "id": ASSIGN_TASK_CANCEL_ID,
                            "type": "reply",
                            "displayText": t("graph.bulter.assign_task.cancel_button"),
                        },
                    ],
                    "interactive_title": t("graph.bulter.assign_task.approval_title"),
                    "text_done": True,
                },
            )
        ],
    }


async def assign_task_approval_response_node(
    state: MessageState, config: RunnableConfig
):
    pending = state.get("pending_assign_task") or {}
    last_message = state["messages"][-1]
    content = str(last_message.content).strip().lower()
    if content == ASSIGN_TASK_CANCEL_ID:
        return {
            "pending_assign_task": None,
            "messages": [
                AIMessage(
                    content=t("graph.bulter.assign_task.cancelled"),
                    additional_kwargs={"text_done": True},
                )
            ],
        }

    runtime = ToolRuntime(
        state=state,
        context=None,
        config=config,
        stream_writer=lambda _: None,
        tool_call_id="assign-task-approval",
        store=None,
    )
    result = await assign_task.coroutine(
        pending.get("task_name", ""),
        pending.get("goal", ""),
        runtime,
    )
    response = t("graph.bulter.assign_task.approved") % (
        result.get("task_name", pending.get("task_name", "")),
        pending.get("goal", ""),
        result.get("status", ""),
        t("graph.bulter.assign_task.next_step"),
    )
    return {
        "pending_assign_task": None,
        "messages": [AIMessage(content=response, additional_kwargs={"text_done": True})],
    }


workflow = StateGraph(MessageState)

workflow.add_node("approval_gate", approval_gate_node)
workflow.add_node("chat", chat_node)
workflow.add_node("assign_task_approval_request", assign_task_approval_request_node)
workflow.add_node("assign_task_approval_response", assign_task_approval_response_node)
workflow.add_node(
    "tools", GraphNode.build_tool_node(SystemTools + MemoryTools + SandboxTools)
)
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "approval_gate")
workflow.add_conditional_edges("approval_gate", route_after_approval_gate)
workflow.add_conditional_edges("chat", route_after_butler_chat)
workflow.add_edge("assign_task_approval_request", "end_node")
workflow.add_edge("assign_task_approval_response", "end_node")
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
