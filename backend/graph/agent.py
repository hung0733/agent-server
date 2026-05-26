import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
    HumanMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.dao import AgentDAO
from backend.db.session import async_session_factory
from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.llm import LLMSet
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import (
    CompletedTurn,
    ConversationMessage,
    ToolCallMessage,
)
from backend.tdai_memory.offload.manager import OffloadManager
from backend.tools.sandbox import SandboxTools
from backend.tools.system import SystemTools, assign_task

logger = logging.getLogger(__name__)

AgentTools = [*SystemTools, *SandboxTools]
ASSIGN_TASK_MAX_RETRIES = 2


async def chat_node(state: MessageState, config: RunnableConfig):
    models: LLMSet = config["configurable"]["models"]  # type: ignore
    involves_secrets: bool = config["configurable"]["involves_secrets"] or False  # type: ignore
    think_mode: bool = config["configurable"]["think_mode"] or False  # type: ignore
    args: Dict[str, Any] = config["configurable"]["args"] or {}  # type: ignore
    sys_prompt: str = config["configurable"]["sys_prompt"] or ""  # type: ignore
    ltm_msg: str = config["configurable"]["ltm_msg"] or ""  # type: ignore
    timelines: list[BaseMessage] = config["configurable"]["timelines"] or ""  # type: ignore

    model_to_use: Optional[BaseChatModel] = models.getModel(2, involves_secrets)
    if not model_to_use:
        raise ValueError(t("graph.agent.llm_model_missing"))

    messages: list[BaseMessage] = []
    if sys_prompt:
        messages.append(SystemMessage(content=sys_prompt))
    if timelines:
        messages += timelines
    if ltm_msg:
        messages.append(AIMessage(content=ltm_msg))

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    messages.append(AIMessage(content="當前時間：%s" % current_time))

    messages += list(state["messages"])

    logger.debug(
        t("graph.agent.chat_node_started"),
        len(messages),
        think_mode,
        bool(args),
    )
    logger.info(messages)

    model_with_tools = _bind_tools(model_to_use, _tools_for_config(config))
    response: AIMessage = await model_to_use.ainvoke(messages)
    GraphNode.log_base_message_response(response)
    response.additional_kwargs = {
        **response.additional_kwargs,
        "datetime": datetime.now(timezone.utc),
        "text_done": True,
    }

    logger.debug(t("graph.agent.chat_node_completed"), len(str(response.content)))
    return {"messages": [response]}


async def end_node(state: MessageState, config: RunnableConfig):
    session_id: str = config["configurable"]["thread_id"] or ""  # type: ignore
    agent_id: str = config["configurable"]["agent_id"] or ""  # type: ignore
    messages: list[BaseMessage] = state["messages"]
    logger.info(messages)

    turn: CompletedTurn = CompletedTurn(
        session_key=session_id,
        user_text="",
        assistant_text="",
        messages=[],
    )

    message: BaseMessage
    for message in messages:
        if isinstance(message, HumanMessage):
            turn.user_text = str(message.content)
            turn.messages.append(
                ConversationMessage(
                    role="user",
                    content=str(message.content),
                    timestamp=int(
                        message.additional_kwargs["datetime"].timestamp() * 1000
                    ),
                )
            )
        elif isinstance(message, AIMessage):
            if message.content:
                turn.assistant_text += str(message.content) + "\n\n"
                turn.messages.append(
                    ConversationMessage(
                        role="assistant",
                        content=str(message.content),
                        timestamp=int(
                            message.additional_kwargs["datetime"].timestamp() * 1000
                        ),
                    )
                )

            if hasattr(message, "tool_calls") and len(message.tool_calls) > 0:
                for tc in getattr(message, "tool_calls", []):
                    args = tc.get("args", {})
                    tool_call_id = str(tc.get("id") or "")
                    tool_name = str(tc.get("name") or "")
                    turn.tool_call.append(
                        ToolCallMessage(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            tool_input=args,
                            tool_result="",
                            timestamp=int(
                                message.additional_kwargs["datetime"].timestamp() * 1000
                            ),
                        )
                    )

        elif isinstance(message, ToolMessage) and message.content:
            for tc in turn.tool_call:
                if tc.tool_call_id == message.tool_call_id:
                    tc.tool_result = str(message.content)

    await MemoryManager.instance().capture(agent_id=agent_id, turn=turn)

    return


def _tools_for_config(config: RunnableConfig) -> Sequence[Any]:
    configurable = config.get("configurable", {})
    if configurable.get("sandbox") is not None:
        return AgentTools
    return SystemTools


def _bind_tools(model: BaseChatModel, tools: Sequence[Any]) -> BaseChatModel:
    bind_tools = getattr(model, "bind_tools", None)
    if not callable(bind_tools):
        return model

    try:
        return bind_tools(tools)
    except NotImplementedError:
        return model


def route_after_chat(state: MessageState) -> str:
    if not state["messages"]:
        return "end_node"

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return "end_node"

    for tool_call in last_message.tool_calls:
        if tool_call.get("name") == "assign_task":
            return "assign_task"

    if last_message.tool_calls:
        return "tools"

    return "end_node"


async def assign_task_node(state: MessageState, config: RunnableConfig):
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return {"messages": []}

    tool_messages: list[ToolMessage] = []
    allowed_agent_names = await _get_allowed_agent_names(config)
    assign_task_config = _with_allowed_agent_names(config, allowed_agent_names)
    for tool_call in last_message.tool_calls:
        if tool_call.get("name") != "assign_task":
            continue

        tool_call_id = str(tool_call.get("id") or "")
        runtime = ToolRuntime(
            state=state,
            context=None,
            config=assign_task_config,
            stream_writer=lambda _: None,
            tool_call_id=tool_call_id,
            store=None,
        )
        result = assign_task.func(
            tool_call.get("args", {}).get("task_json", ""),
            runtime,
        )
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call_id,
            )
        )

    return {"messages": tool_messages}


def route_after_assign_task(state: MessageState) -> str:
    if not _last_assign_task_rejected(state):
        return "end_node"
    if _assign_task_rejection_count(state) <= ASSIGN_TASK_MAX_RETRIES:
        return "chat"
    return "end_node"


async def _get_allowed_agent_names(config: RunnableConfig) -> list[str]:
    configurable = config.get("configurable", {})
    configured_names = configurable.get("assign_task_allowed_agent_names")
    if isinstance(configured_names, list):
        return [
            name for name in configured_names if isinstance(name, str) and name.strip()
        ]

    user_db_id = configurable.get("user_db_id")
    if user_db_id is None:
        return []

    async with async_session_factory() as session:
        agents = await AgentDAO(session).list_by_user_id(int(user_db_id))

    return [agent.name for agent in agents if agent.is_active]


def _with_allowed_agent_names(
    config: RunnableConfig, allowed_agent_names: list[str]
) -> RunnableConfig:
    return {
        **config,
        "configurable": {
            **config.get("configurable", {}),
            "assign_task_allowed_agent_names": allowed_agent_names,
        },
    }


def _last_assign_task_rejected(state: MessageState) -> bool:
    if not state["messages"]:
        return False
    last_message = state["messages"][-1]
    if not isinstance(last_message, ToolMessage):
        return False
    payload = _tool_message_json(last_message)
    return payload.get("accepted") is False


def _assign_task_rejection_count(state: MessageState) -> int:
    count = 0
    for message in state["messages"]:
        if not isinstance(message, ToolMessage):
            continue
        payload = _tool_message_json(message)
        if payload.get("accepted") is False:
            count += 1
    return count


def _tool_message_json(message: ToolMessage) -> dict[str, Any]:
    content = (
        message.content if isinstance(message.content, str) else str(message.content)
    )
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("assign_task", assign_task_node)
workflow.add_node("tools", ToolNode(SandboxTools))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_conditional_edges("assign_task", route_after_assign_task)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
