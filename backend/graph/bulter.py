import json
import logging
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.dao import AgentDAO
from backend.db.session import async_session_factory
from backend.graph.agent import chat_node, end_node, route_after_chat
from backend.graph.graph_node import MessageState
from backend.tools.sandbox import SandboxTools
from backend.tools.system import assign_task

logger = logging.getLogger(__name__)


workflow = StateGraph(MessageState)

workflow.add_node("chat", chat_node)
workflow.add_node("tools", ToolNode(SandboxTools))
workflow.add_node("end_node", end_node)

workflow.add_edge(START, "chat")
workflow.add_conditional_edges("chat", route_after_chat)
workflow.add_edge("tools", "chat")
workflow.add_edge("end_node", END)


graph = workflow.compile()
