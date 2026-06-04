from datetime import datetime, timezone
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
)
from backend.dao.assigned_task import AssignedTaskDAO
from backend.db.session import async_session_factory
from backend.graph.agent import chat_node, end_node, route_after_chat
from backend.graph.graph_node import GraphNode, MessageState
from backend.graph.interrupt_nodes import human_review_node, route_after_human_review
from backend.i18n import t
from backend.tools.brainstormer import ask_user_question, submit_html_plan_for_approval

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


async def pre_user_question_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:
    messages: list[BaseMessage] = list(state["messages"])
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "ask_user_question":
                args = tool_call.get("args") or {}
                question = args.get("question", "?")

                logger.info(f"User question requested: {question}")

                message = await ask_user_question.coroutine(**args)  # type: ignore

                question_msg = AIMessage(
                    content=message,
                    additional_kwargs={"datetime": datetime.now(timezone.utc)},
                )

                messages.append(question_msg)
                GraphNode.store_message(config, messages)

                if GraphNode.is_butler_asking(config):
                    GraphNode.store_user_message(config, [question_msg])

                return {
                    "messages": [question_msg],
                    "human_review_node": "chat",
                    "human_review_data": args,
                    "human_review_result": None,
                    "human_review_approve": False,
                }

    return {
        "messages": [ToolMessage(content=t("graph.bulter.assign_task.invalid_call"))]
    }


async def pre_submit_approval_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:
    messages: list[BaseMessage] = list(state["messages"])
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "submit_html_plan_for_approval":
                args = tool_call.get("args") or {}

                message = await submit_html_plan_for_approval.coroutine(**args)  # type: ignore
                await _save_html_plan_to_task_step(config, args)

                approval_msg = AIMessage(
                    content=message,
                    additional_kwargs={"datetime": datetime.now(timezone.utc)},
                )

                messages.append(approval_msg)
                GraphNode.store_message(config, messages)

                if GraphNode.is_butler_asking(config):
                    GraphNode.store_user_message(config, [approval_msg])

                return {
                    "messages": [approval_msg],
                    "human_review_node": "submit_approval_node",
                    "human_review_data": args,
                    "human_review_result": None,
                    "human_review_approve": True,
                }

    return {
        "messages": [ToolMessage(content=t("graph.bulter.assign_task.invalid_call"))]
    }


async def _save_html_plan_to_task_step(
    config: RunnableConfig, args: dict[str, Any]
) -> None:
    html_plan = str(args.get("html_plan") or "").strip()
    session_db_id = GraphNode.get_configure(config, "session_db_id", None)
    if not html_plan or session_db_id is None:
        return

    async with async_session_factory() as session:
        await AssignedTaskDAO(session).update_step_output_html_by_session_id(
            session_db_id=int(session_db_id),
            output_html=html_plan,
        )
        await session.commit()


async def submit_approval_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:

    message = AIMessage(
        content=t("graph.brainstormer.submit_approval.approved_message"),
        additional_kwargs={"datetime": datetime.now(timezone.utc)},
    )

    if GraphNode.is_butler_asking(config):
        GraphNode.store_user_message(config, [message])

    return {
        "messages": [message],
        "human_review_node": None,
        "human_review_data": None,
        "human_review_result": None,
        "human_review_approve": None,
    }


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("human_review_node", human_review_node)
workflow.add_node("tools", GraphNode.build_tool_node(GraphNode.get_all_tools()))
workflow.add_node("end_node", end_node)
workflow.add_node("pre_user_question_node", pre_user_question_node)
workflow.add_node("pre_submit_approval_node", pre_submit_approval_node)
workflow.add_node("submit_approval_node", submit_approval_node)


workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat_brainstormer)
workflow.add_conditional_edges("human_review_node", route_after_human_review)
workflow.add_edge("pre_user_question_node", "human_review_node")
workflow.add_edge("pre_submit_approval_node", "human_review_node")
workflow.add_edge("submit_approval_node", "end_node")
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
