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

_REVIEW_KEYS = {"seqNo", "review_suggest"}


def parse_reviewer_review_json(content: str) -> list[dict[str, object]]:
    output_json = _strip_json_fence(content)
    parsed = json.loads(output_json)
    if not isinstance(parsed, list):
        raise ValueError(t("graph.reviewer.invalid_json"))

    for item in parsed:
        _validate_review_item(item)

    return parsed


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
    return content.strip()


def _validate_review_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise ValueError(t("graph.reviewer.invalid_json"))
    if set(item) != _REVIEW_KEYS:
        raise ValueError(t("graph.reviewer.invalid_json"))
    if not isinstance(item["seqNo"], int):
        raise ValueError(t("graph.reviewer.invalid_json"))
    if not isinstance(item["review_suggest"], str):
        raise ValueError(t("graph.reviewer.invalid_json"))


async def handle_review_json_node(
    state: MessageState, config: RunnableConfig
) -> dict[str, Any]:
    messages: list[BaseMessage] = list(state["messages"])
    last_message = messages[-1] if messages else None
    if not isinstance(last_message, AIMessage):
        return _reviewer_error_message(t("graph.reviewer.invalid_json"))

    try:
        review_items = parse_reviewer_review_json(str(last_message.content or ""))
    except (json.JSONDecodeError, ValueError):
        logger.warning(t("graph.reviewer.invalid_json"))
        return _reviewer_error_message(t("graph.reviewer.invalid_json"))

    session_db_id = GraphNode.get_configure(config, "session_db_id", None)
    if session_db_id is None:
        logger.warning(t("graph.reviewer.missing_session"))
        return _reviewer_error_message(t("graph.reviewer.save_failed"))

    saved = await _complete_reviewer_step(int(session_db_id), review_items)
    if not saved:
        logger.warning(t("graph.reviewer.step_not_found"), session_db_id)
        return _reviewer_error_message(t("graph.reviewer.save_failed"))

    logger.info(t("graph.reviewer.saved"), session_db_id)
    return {
        "messages": [
            AIMessage(
                content=t("graph.reviewer.saved_message"),
                additional_kwargs={"datetime": datetime.now(timezone.utc)},
            )
        ]
    }


async def _complete_reviewer_step(
    session_db_id: int, review_items: list[dict[str, object]]
) -> bool:
    async with async_session_factory() as session:
        saved = await AssignedTaskDAO(
            session
        ).complete_reviewer_step_with_review_json(
            session_db_id=session_db_id,
            review_items=review_items,
        )
        if saved:
            await session.commit()
        return saved


def _reviewer_error_message(content: str) -> dict[str, Any]:
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
workflow.add_node("handle_review_json_node", handle_review_json_node)
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_edge("chat", "handle_review_json_node")
workflow.add_edge("handle_review_json_node", "end_node")
workflow.add_edge("end_node", END)


graph = workflow.compile()
