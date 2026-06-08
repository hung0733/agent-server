from datetime import datetime, timezone
import json
import logging
from typing import Annotated, Any, Dict, NotRequired, Optional, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
    HumanMessage,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, ToolRuntime

from backend.channels import EvolutionWhatsAppChannel
from backend.dao.agent import AgentDAO
from backend.dao.user_acc import UserAccDAO
from backend.db.session import async_session_factory
from backend.dto.agent_msg_hist import AgentMsgHistCreate
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.llm.types import StreamChunk
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import CompletedTurn
from backend.tools.brainstormer import BrainstormerTools
from backend.tools.memory import MemoryTools
from backend.tools.sandbox import SandboxTools
from backend.tools.bulter import BulterTools
from backend.utils.message import MsgUtil
from backend.utils.tools import Tools

logger = logging.getLogger(__name__)


def _replace_with_last(left: list, right: list):
    """至少保留一個由 HumanMessage 開始的完整對話輪次。

    邏輯：
    1. 從 left 中找到最後一個 HumanMessage 的位置
    2. 保留該 HumanMessage 及其之後的所有消息
    3. 再加上新傳入的 right 消息
    """
    if right:
        for msg in right:
            if isinstance(msg, HumanMessage):
                return right

    # 從 left 中找到最後一個 HumanMessage 的位置
    keep_from = 0
    for i in range(len(left) - 1, -1, -1):
        if isinstance(left[i], HumanMessage):
            keep_from = i
            break

    # 保留最後一個 HumanMessage 開始的消息 + 新消息
    if not right:
        return left[keep_from:]
    return left[keep_from:] + right


class MessageState(TypedDict):
    """Minimal state for nodes that only need messages."""

    messages: Annotated[list[BaseMessage], _replace_with_last]
    human_review_node: Optional[str]
    human_review_data: Optional[Dict[str, Any]]
    human_review_result: Optional[str]
    human_review_approve: Optional[bool]


class GraphNode:
    RUNTIME_MODEL_ARG_KEYS = ("temperature", "top_p", "presence_penalty")
    RUNTIME_EXTRA_BODY_ARG_KEYS = ("top_k", "repetition_penalty", "min_p")
    RUNTIME_MODEL_ARG_DEFAULTS = {
        False: {
            "temperature": 0.7,
            "top_p": 0.8,
            "presence_penalty": 1.5,
            "top_k": 20,
            "repetition_penalty": 1.0,
            "min_p": 0.0,
        },
        True: {
            "temperature": 1.0,
            "top_p": 0.95,
            "presence_penalty": 1.5,
            "top_k": 20,
            "repetition_penalty": 1.0,
            "min_p": 0.0,
        },
    }

    @staticmethod
    def is_butler_asking(config: RunnableConfig) -> bool:
        return GraphNode.get_configure(
            config, "sender_agent_db_id", None
        ) is not None and not GraphNode.get_configure(
            config, "sender_is_sub_agent", False
        )

    @staticmethod
    def store_user_message(config: RunnableConfig, messages: list[BaseMessage]) -> None:
        session_id: str = GraphNode.get_configure(config, "sender_agent_session_id", "")
        session_db_id: int = GraphNode.get_configure(
            config, "sender_agent_session_db_id", 0
        )
        step_id: str = GraphNode.get_configure(config, "step_id", "")
        agent_id: str = GraphNode.get_configure(config, "sender_agent_id", "")
        conversation_metadata = {
            "conversation_kind": "user_to_agent",
            "sender_name": GraphNode.get_configure(config, "user_name", ""),
            "sender_type": "user",
            "recv_name": GraphNode.get_configure(config, "recv_name", ""),
            "recv_type": GraphNode.get_configure(config, "recv_type", "agent"),
        }

        user_msg, assistant_msg, cm, tcm = MsgUtil.base_msg_to_tdai_memory_rec(
            messages, conversation_metadata
        )

        dtos: list[AgentMsgHistCreate] = MsgUtil.base_msg_to_msg_hist_rec(
            messages, session_db_id, step_id, conversation_metadata
        )

        turn: CompletedTurn = CompletedTurn(
            session_key=session_id,
            user_text=user_msg,
            assistant_text=assistant_msg,
            messages=cm,
            tool_call=tcm,
            metadata=conversation_metadata,
        )

        Tools.start_async_task(
            MemoryManager.instance().capture(agent_id=agent_id, turn=turn)
        )

        Tools.start_async_task(MsgUtil.save_agent_msg_hist(dtos))

    @staticmethod
    def get_tool_runtime(state: MessageState, config: RunnableConfig) -> ToolRuntime:
        return ToolRuntime(
            state=state,
            context=None,
            config=config,
            stream_writer=lambda _: None,
            tool_call_id=None,
            store=None,
        )  # type: ignore

    @staticmethod
    def store_message(config: RunnableConfig, messages: list[BaseMessage]) -> None:
        session_id: str = GraphNode.get_configure(config, "thread_id", "")
        session_db_id: int = GraphNode.get_configure(config, "session_db_id", 0)
        step_id: str = GraphNode.get_configure(config, "step_id", "")
        agent_id: str = GraphNode.get_configure(config, "agent_id", "")
        conversation_metadata = {
            "conversation_kind": GraphNode.get_configure(
                config, "conversation_kind", "unknown"
            ),
            "sender_name": GraphNode.get_configure(config, "sender_name", ""),
            "sender_type": GraphNode.get_configure(config, "sender_type", "unknown"),
            "recv_name": GraphNode.get_configure(config, "recv_name", ""),
            "recv_type": GraphNode.get_configure(config, "recv_type", "agent"),
        }

        user_msg, assistant_msg, cm, tcm = MsgUtil.base_msg_to_tdai_memory_rec(
            messages, conversation_metadata
        )

        dtos: list[AgentMsgHistCreate] = MsgUtil.base_msg_to_msg_hist_rec(
            messages, session_db_id, step_id, conversation_metadata
        )

        turn: CompletedTurn = CompletedTurn(
            session_key=session_id,
            user_text=user_msg,
            assistant_text=assistant_msg,
            messages=cm,
            tool_call=tcm,
            metadata=conversation_metadata,
        )

        Tools.start_async_task(
            MemoryManager.instance().capture(agent_id=agent_id, turn=turn)
        )

        Tools.start_async_task(MsgUtil.save_agent_msg_hist(dtos))

    @staticmethod
    def get_all_tools() -> list[Any]:
        return MemoryTools + BulterTools + BrainstormerTools + SandboxTools

    @staticmethod
    def build_tool_node(tools: list[Any]) -> ToolNode:
        return ToolNode(tools, handle_tool_errors=GraphNode.format_tool_error)

    @staticmethod
    def format_tool_error(error: Exception) -> str:
        return t("graph.agent.tool_error") % str(error)

    @staticmethod
    def build_tools(config: RunnableConfig, model: ChatOpenAI) -> ChatOpenAI:
        bind_tools = getattr(model, "bind_tools", None)
        if not callable(bind_tools):
            return model

        tools: list[Any] = list(MemoryTools)
        if GraphNode.get_configure(config, "agent_type", "") == "bulter":
            tools += BulterTools
        if GraphNode.get_configure(config, "agent_type", "") == "brainstormer":
            tools += BrainstormerTools
        if (GraphNode.get_configure(config, "sandbox")) is not None:
            tools += SandboxTools

        tool_names = [
            str(getattr(tool, "name", None) or getattr(tool, "__name__", ""))
            for tool in tools
        ]
        logger.info(t("graph.agent.tools_loaded"), ", ".join(tool_names))

        try:
            if GraphNode.get_configure(config, "agent_type", "") == "brainstormer":
                return bind_tools(tools, tool_choice="required")  # type: ignore
            return bind_tools(tools)  # type: ignore
        except TypeError:
            return bind_tools(tools)  # type: ignore
        except NotImplementedError:
            return model

    @staticmethod
    def pack_message(state: MessageState, config: RunnableConfig) -> list[BaseMessage]:
        sys_prompt: str = GraphNode.get_configure(config, "sys_prompt", "")
        ltm_msg: str = GraphNode.get_configure(config, "ltm_msg", "")
        timelines: list[BaseMessage] = GraphNode.get_configure(config, "timelines", [])

        messages: list[BaseMessage] = []
        if sys_prompt:
            messages.append(SystemMessage(content=sys_prompt))

        if timelines:
            messages += timelines

        if ltm_msg:
            messages.append(AIMessage(content=ltm_msg))

        current_time = datetime.now(timezone.utc).strftime(
            "%A, %B %-d, %Y — %I:%M %p %Z"
        )
        messages.append(
            AIMessage(content=t("graph.agent.current_time_message") % current_time)
        )

        messages += list(state["messages"])

        return messages

    @staticmethod
    def get_configure(config: RunnableConfig, name: str, dflt_val: Any = None) -> Any:
        if config and config["configurable"] and config["configurable"][name]:  # type: ignore
            return config["configurable"][name]  # type: ignore

        return dflt_val

    @staticmethod
    def with_runtime_model_args(
        config: RunnableConfig, model: ChatOpenAI
    ) -> ChatOpenAI:
        if not isinstance(model, ChatOpenAI):
            return model

        configurable = config.get("configurable", {}) if config else {}
        args = configurable.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        think_mode = bool(configurable.get("think_mode"))
        runtime_args: dict[str, Any] = {}
        qwen36_model = model.model.lower().startswith("qwen3.6")
        if qwen36_model:
            runtime_args.update(GraphNode.RUNTIME_MODEL_ARG_DEFAULTS[think_mode])

        runtime_args.update(
            {
                key: args[key]
                for key in (
                    *GraphNode.RUNTIME_MODEL_ARG_KEYS,
                    *GraphNode.RUNTIME_EXTRA_BODY_ARG_KEYS,
                )
                if key in args and args[key] is not None
            }
        )

        if not runtime_args:
            return model

        update = {
            key: runtime_args[key]
            for key in GraphNode.RUNTIME_MODEL_ARG_KEYS
            if key in runtime_args and runtime_args[key] is not None
        }
        runtime_extra_body = {
            key: runtime_args[key]
            for key in GraphNode.RUNTIME_EXTRA_BODY_ARG_KEYS
            if key in runtime_args and runtime_args[key] is not None
        }
        if qwen36_model:
            runtime_extra_body = {
                "chat_template_kwargs": {"enable_thinking": think_mode},
                **runtime_extra_body,
            }
        if runtime_extra_body:
            update["extra_body"] = {
                **GraphNode._model_extra_body(model),
                **runtime_extra_body,
            }

        return model.model_copy(update=update)

    @staticmethod
    def _model_extra_body(model: ChatOpenAI) -> dict[str, Any]:
        extra_body: dict[str, Any] = {}
        if isinstance(model.extra_body, dict):
            extra_body.update(model.extra_body)

        return extra_body

    @staticmethod
    async def send_user_whatsapp(
        user_db_id: int | None, agent_db_id: int | None, content: str
    ) -> str | None:
        content = str(content or "").strip()
        if not user_db_id or not agent_db_id or not content:
            logger.info(
                t("graph_node.user_whatsapp_missing_fields"),
                user_db_id,
                agent_db_id,
            )
            return None

        async with async_session_factory() as session:
            user = await UserAccDAO(session).get_by_id(user_db_id)
            agent = await AgentDAO(session).get_by_id(agent_db_id)

        phoneno = getattr(user, "phoneno", None)
        whatsapp_instance = getattr(agent, "whatsapp_instance", None)
        whatsapp_key = getattr(agent, "whatsapp_key", None)

        if (
            not user
            or not agent
            or not phoneno
            or not whatsapp_instance
            or not whatsapp_key
        ):
            logger.info(
                t("graph_node.user_whatsapp_missing_fields"),
                user_db_id,
                agent_db_id,
            )
            return None

        channel = EvolutionWhatsAppChannel(
            whatsapp_instance=whatsapp_instance,
            whatsapp_key=whatsapp_key,
        )
        try:
            resp = await channel.send_text(phoneno, content)
        except Exception:
            logger.exception(
                t("graph_node.user_whatsapp_send_failed"),
                user_db_id,
                agent_db_id,
            )
            return None
        finally:
            await channel.close()

        message_id = GraphNode._extract_evolution_message_id(resp)
        logger.info(
            t("graph_node.user_whatsapp_sent"),
            user_db_id,
            agent_db_id,
            message_id,
        )
        return message_id

    @staticmethod
    def _extract_evolution_message_id(evolution_response: dict[str, Any]) -> str | None:
        if not isinstance(evolution_response, dict):
            return None
        key = evolution_response.get("key")
        if not isinstance(key, dict):
            return None
        message_id = key.get("id")
        return message_id if isinstance(message_id, str) else None

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
        sender_type: str = "",
        recv_type: str = "agent",
        conversation_kind: str = "",
        user_db_id: int | None = None,
        user_name: str = "",
        session_db_id: int | None = None,
        agent_db_id: int | None = None,
        agent_id: str = "",
        agent_type: str = "",
        sandbox: Any | None = None,
        ltm_msg: str = "",
        timelines: list[BaseMessage] = [],
        sender_agent_id: str = "",
        sender_agent_db_id: int | None = None,
        sender_agent_session_db_id: int | None = None,
        sender_agent_session_id: str | None = None,
        sender_is_sub_agent: bool = False,
        recv_is_sub_agent: bool = False,
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
                "sender_type": sender_type,
                "recv_type": recv_type,
                "conversation_kind": conversation_kind,
                "user_db_id": user_db_id,
                "user_name": user_name,
                "agent_db_id": agent_db_id,
                "agent_id": agent_id,
                "agent_type": agent_type,
                "sandbox": sandbox,
                "ltm_msg": ltm_msg,
                "timelines": timelines,
                "session_db_id": session_db_id,
                "sender_agent_db_id": sender_agent_db_id,
                "sender_agent_id": sender_agent_id,
                "sender_agent_session_db_id": sender_agent_session_db_id,
                "sender_agent_session_id": sender_agent_session_id,
                "sender_is_sub_agent": sender_is_sub_agent,
                "recv_is_sub_agent": recv_is_sub_agent,
            }
        }
