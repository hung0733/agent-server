from datetime import datetime, timezone
import logging
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
from backend.tools.brainstormer import ask_user_question

logger = logging.getLogger(__name__)


def route_after_chat_brainstormer(state: MessageState) -> str:
    if not state.get("messages"):
        return "end_node"

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "ask_user_question":
                return "pre_user_question_node"
            elif tool_call.get("name") == "submit_html_plan_for_approval":
                return "pre_submit_approval_node"

    return route_after_chat(state)


def pre_user_question_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "ask_user_question":
                args = tool_call.get("args") or {}
                question = args.get("question", "?")

                logger.info(f"User question requested: {question}")

                message = ask_user_question.coroutine(**args)  # type: ignore

                question_msg = AIMessage(
                    content=message,
                    additional_kwargs={"datetime": datetime.now(timezone.utc)},
                )

                if GraphNode.is_butler_asking(config):
                    GraphNode.store_user_message(config, [question_msg])

                return {
                    "messages": [question_msg],
                    "human_review_node": "chat_node",
                    "human_review_data": args,
                    "human_review_result": None,
                }

    return {
        "messages": [ToolMessage(content=t("graph.bulter.assign_task.invalid_call"))]
    }


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("human_review_node", human_review_node)
workflow.add_node("tools", GraphNode.build_tool_node(GraphNode.get_all_tools()))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat_brainstormer)
workflow.add_conditional_edges("human_review_node", route_after_human_review)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
