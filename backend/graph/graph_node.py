from typing import Annotated, Any, Dict, Optional, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from backend.llm.llm import LLMSet


def _replace_with_last(left: list, right: list):
    """至少保留一個由 HumanMessage 開始的完整對話輪次。

    邏輯：
    1. 從 left 中找到最後一個 HumanMessage 的位置
    2. 保留該 HumanMessage 及其之後的所有消息
    3. 再加上新傳入的 right 消息
    """
    if not right:
        return left

    # 從 left 中找到最後一個 HumanMessage 的位置
    keep_from = 0
    for i in range(len(left) - 1, -1, -1):
        if isinstance(left[i], HumanMessage):
            keep_from = i
            break

    # 保留最後一個 HumanMessage 開始的消息 + 新消息
    return left[keep_from:] + right


class MessageState(TypedDict):
    """Minimal state for nodes that only need messages."""

    messages: Annotated[list[BaseMessage], _replace_with_last]

class GraphNode:
    @staticmethod
    def prepare_chat_node_config(
        thread_id: str,
        models: LLMSet,
        sys_prompt: str,
        involves_secrets: bool,
        think_mode: Optional[bool],
        step_id: str = "",
        args: Optional[Dict[str, Any]] = None,
        sender_name: str = "",
        recv_name: str = "",
        stm_trigger_token: int = 0,
        stm_summary_token: int = 0,
    ) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "models": models,
                "sys_prompt": sys_prompt,
                "involves_secrets": involves_secrets,
                "think_mode": think_mode,
                "args": args,
                "step_id": step_id,
                "sender_name": sender_name,
                "recv_name": recv_name,
                "stm_trigger_token": stm_trigger_token,
                "stm_summary_token": stm_summary_token,
            }
        }