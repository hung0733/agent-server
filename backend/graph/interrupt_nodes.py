import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet

logger = logging.getLogger(__name__)

APPROVE_LABEL = "approve"
CANCEL_LABEL = "cancel"
OTHER_LABEL = "other"


async def human_review_node(state: MessageState, config: RunnableConfig) -> dict:
    messages: list[BaseMessage] = state["messages"]
    GraphNode.store_message(config, messages)

    last_message: BaseMessage = messages[-1]

    user_message: HumanMessage = interrupt(
        {"type": "human_review", "message": last_message}
    )

    messages.append(user_message)

    review_result: str = await _classify_approval_reply(messages, config)

    return {
        "messages": [user_message],
        "human_review_result": review_result,
    }


def route_after_human_review(state: MessageState) -> str:
    human_review_result = state.get("human_review_result")
    if human_review_result == APPROVE_LABEL and state.get("human_review_node"):
        return str(state.get("human_review_node"))
    elif human_review_result == CANCEL_LABEL:
        return "end_node"
    else:
        return "chat"


async def _classify_approval_reply(
    messages: list[BaseMessage], config: RunnableConfig
) -> str:
    question_message = messages[-2]
    user_reply_message = messages[-1]

    classification_prompt = t("graph.interrupt.classification_prompt") % (
        (
            question_message.content
            if isinstance(question_message, AIMessage)
            else str(question_message)
        ),
        (
            user_reply_message.content
            if isinstance(user_reply_message, HumanMessage)
            else str(user_reply_message)
        ),
    )

    try:
        client = await LLMSet.getRteModel()
        messages = [SystemMessage(content=classification_prompt)]
        response = await client.ainvoke(messages)
        content = client.get_resp_content(response).strip().lower()
    except Exception:
        logger.exception(t("graph.interrupt.classification_failed"))
        content = ""

    if APPROVE_LABEL in content:
        return APPROVE_LABEL
    if CANCEL_LABEL in content:
        return CANCEL_LABEL
    return OTHER_LABEL
