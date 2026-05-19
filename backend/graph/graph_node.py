import json
import logging
from typing import Annotated, Any, Dict, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.llm.types import StreamChunk

logger = logging.getLogger(__name__)


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
    def stream_chunks_to_content(chunks: list[StreamChunk]) -> str:
        return "".join(
            chunk.content or ""
            for chunk in chunks
            if chunk.chunk_type == "content" and chunk.content
        )

    @staticmethod
    def stream_chunks_to_message(chunks: list[StreamChunk]) -> AIMessage | ToolMessage:
        tool_result_chunks = [
            chunk for chunk in chunks if chunk.chunk_type == "tool_result"
        ]
        if tool_result_chunks:
            return GraphNode._stream_chunks_to_tool_message(tool_result_chunks)

        content = GraphNode.stream_chunks_to_content(chunks)
        reasoning_content = "".join(
            chunk.content or ""
            for chunk in chunks
            if chunk.chunk_type == "think" and chunk.content
        )
        tool_calls = [
            GraphNode._tool_call_from_chunk(chunk)
            for chunk in chunks
            if chunk.chunk_type == "tool"
        ]

        additional_kwargs: dict[str, Any] = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content

        return AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _stream_chunks_to_tool_message(chunks: list[StreamChunk]) -> ToolMessage:
        first_chunk = chunks[0]
        data = first_chunk.data or {}
        tool_call_id = data.get("tool_call_id")
        if not tool_call_id:
            tool_call = data.get("tool_call")
            if isinstance(tool_call, dict):
                tool_call_id = tool_call.get("id")

        if not tool_call_id:
            raise ValueError(t("graph_node.tool_result_missing_tool_call_id"))

        content = "".join(chunk.content or "" for chunk in chunks if chunk.content)
        return ToolMessage(content=content, tool_call_id=str(tool_call_id))

    @staticmethod
    def _tool_call_from_chunk(chunk: StreamChunk) -> dict[str, Any]:
        data = chunk.data or {}
        tool_call = data.get("tool_call")
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
            args = tool_call.get("args", {})
            tool_call_id = tool_call.get("id")
        else:
            function = data.get("function")
            if not isinstance(function, dict):
                raise ValueError(t("graph_node.tool_call_missing_function"))
            name = function.get("name")
            args = function.get("arguments", {})
            tool_call_id = data.get("id")

        if not name:
            raise ValueError(t("graph_node.tool_call_missing_function"))

        parsed_args = GraphNode._parse_tool_call_args(args)
        return {
            "name": str(name),
            "args": parsed_args,
            "id": str(tool_call_id) if tool_call_id else None,
        }

    @staticmethod
    def _parse_tool_call_args(args: Any) -> dict[str, Any]:
        if args is None or args == "":
            raise ValueError(t("graph_node.tool_call_invalid_arguments"))
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                parsed_args = json.loads(args)
            except json.JSONDecodeError as exc:
                raise ValueError(t("graph_node.tool_call_invalid_arguments")) from exc
            if isinstance(parsed_args, dict):
                return parsed_args

        raise ValueError(t("graph_node.tool_call_invalid_arguments"))

    @staticmethod
    def log_stream_chunk_response(chunk: StreamChunk) -> None:
        if chunk.chunk_type == "content":
            logger.info(
                t("graph.agent.chat_node_content_chunk_received"),
                len(chunk.content or ""),
            )
        elif chunk.chunk_type == "tool":
            logger.info(
                t("graph.agent.chat_node_tool_chunk_received"),
                chunk.content or GraphNode._tool_name_from_chunk(chunk),
            )
        elif chunk.chunk_type == "tool_result":
            logger.info(
                t("graph.agent.chat_node_tool_result_chunk_received"),
                len(chunk.content or ""),
            )

    @staticmethod
    def log_base_message_response(message: BaseMessage) -> None:
        content = (
            message.content
            if isinstance(message.content, str)
            else str(message.content)
        )
        if content:
            logger.info(t("graph.agent.chat_node_content_chunk_received"), len(content))

        for tool_call in getattr(message, "tool_calls", []) or []:
            logger.info(
                t("graph.agent.chat_node_tool_chunk_received"),
                tool_call.get("name", ""),
            )

    @staticmethod
    def _tool_name_from_chunk(chunk: StreamChunk) -> str:
        data = chunk.data or {}
        tool_call = data.get("tool_call")
        if isinstance(tool_call, dict):
            return str(tool_call.get("name") or "")

        function = data.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return ""

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
