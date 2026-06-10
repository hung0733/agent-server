import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.dao.assigned_task import AssignedTaskDAO
from backend.db.session import async_session_factory
from backend.graph.agent import chat_node, end_node
from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t

logger = logging.getLogger(__name__)

_STEP_KEYS = {"agent_type", "title", "goal", "dependsOn", "status", "seq_no"}
_AGENT_TYPES = {"engineer", "researcher", "writer", "reviewer"}
_STATUSES = {"PENDING", "BLOCKED"}


def parse_assigned_task_step_json(content: str) -> str:
    output_json = _strip_json_fence(content)
    parsed = json.loads(output_json)
    if not isinstance(parsed, list):
        raise ValueError(t("graph.planner.invalid_json"))

    for item in parsed:
        _validate_step_item(item)

    return output_json


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
    return content.strip()


def _validate_step_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise ValueError(t("graph.planner.invalid_json"))
    if set(item) != _STEP_KEYS:
        raise ValueError(t("graph.planner.invalid_json"))
    if item["agent_type"] not in _AGENT_TYPES:
        raise ValueError(t("graph.planner.invalid_json"))
    if not isinstance(item["title"], str) or not item["title"].strip():
        raise ValueError(t("graph.planner.invalid_json"))
    if not isinstance(item["goal"], str) or not item["goal"].strip():
        raise ValueError(t("graph.planner.invalid_json"))
    if item["dependsOn"] is not None and not isinstance(item["dependsOn"], int):
        raise ValueError(t("graph.planner.invalid_json"))
    if item["status"] not in _STATUSES:
        raise ValueError(t("graph.planner.invalid_json"))
    if not isinstance(item["seq_no"], int):
        raise ValueError(t("graph.planner.invalid_json"))


async def save_assigned_task_step_json_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:
    messages: list[BaseMessage] = list(state["messages"])
    last_message = messages[-1] if messages else None
    if not isinstance(last_message, AIMessage):
        return _planner_error_message(t("graph.planner.invalid_json"))

    try:
        output_json = parse_assigned_task_step_json(str(last_message.content or ""))
    except (json.JSONDecodeError, ValueError):
        logger.warning(t("graph.planner.invalid_json"))
        return _planner_error_message(t("graph.planner.invalid_json"))

    session_db_id = GraphNode.get_configure(config, "session_db_id", None)
    if session_db_id is None:
        logger.warning(t("graph.planner.missing_session"))
        return _planner_error_message(t("graph.planner.save_failed"))

    saved = await _complete_planner_step(int(session_db_id), output_json)
    if not saved:
        logger.warning(t("graph.planner.step_not_found"), session_db_id)
        return _planner_error_message(t("graph.planner.save_failed"))

    logger.info(t("graph.planner.saved"), session_db_id)
    return {
        "messages": [
            AIMessage(
                content=t("graph.planner.saved_message"),
                additional_kwargs={"datetime": datetime.now(timezone.utc)},
            )
        ]
    }


async def _complete_planner_step(
    session_db_id: int, planned_task_step_json: str
) -> bool:
    async with async_session_factory() as session:
        saved = await AssignedTaskDAO(
            session
        ).complete_planner_step_with_planned_task_step_json(
            session_db_id=session_db_id,
            planned_task_step_json=planned_task_step_json,
        )
        if saved:
            await session.commit()
        return saved


def _planner_error_message(content: str) -> dict[str, Any]:
    return {
        "messages": [
            AIMessage(
                content=content,
                additional_kwargs={"datetime": datetime.now(timezone.utc)},
            )
        ]
    }


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("save_assigned_task_step_json_node", save_assigned_task_step_json_node)
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_edge("chat", "save_assigned_task_step_json_node")
workflow.add_edge("save_assigned_task_step_json_node", "end_node")
workflow.add_edge("end_node", END)


graph = workflow.compile()
