import logging
from typing import Any, Literal

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field

from backend.i18n import t
from backend.tdai_memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class MemorySearchArgs(BaseModel):
    query: str = Field(description=t("tools.memory.query.description"))
    top_k: int = Field(default=5, description=t("tools.memory.top_k.description"))
    strategy: Literal["keyword", "embedding", "hybrid"] = Field(
        default="hybrid", description=t("tools.memory.search.strategy.description")
    )
    score_threshold: float = Field(
        default=0.3, description=t("tools.memory.score_threshold.description")
    )
    type_filter: Literal["persona", "episodic", "instruction"] | None = Field(
        default=None, description=t("tools.memory.type_filter.description")
    )
    scene_filter: str | None = Field(
        default=None, description=t("tools.memory.scene_filter.description")
    )


class ConversationSearchArgs(BaseModel):
    query: str = Field(description=t("tools.memory.query.description"))
    current_session_only: bool = Field(
        description=t("tools.memory.current_session_only.description")
    )
    top_k: int = Field(default=5, description=t("tools.memory.top_k.description"))
    strategy: Literal["keyword", "embedding"] = Field(
        default="keyword",
        description=t("tools.memory.conversation_search.strategy.description"),
    )


@tool(
    args_schema=MemorySearchArgs,
    description=t("tools.memory.search.description"),
)
async def tdai_memory_search(
    query: str,
    runtime: ToolRuntime,
    top_k: int = 5,
    strategy: Literal["keyword", "embedding", "hybrid"] = "hybrid",
    score_threshold: float = 0.3,
    type_filter: Literal["persona", "episodic", "instruction"] | None = None,
    scene_filter: str | None = None,
) -> dict[str, Any]:
    """Search structured TDAI memories for the configured agent."""
    agent_id = _agent_id_from_runtime(runtime)
    logger.info(t("tools.memory.search.started"), runtime.tool_call_id, agent_id)
    result = await MemoryManager.instance().search_memories(
        agent_id=agent_id,
        query=query,
        top_k=top_k,
        strategy=strategy,
        score_threshold=score_threshold,
        type_filter=type_filter,
        scene_filter=scene_filter,
    )
    logger.info(
        t("tools.memory.search.completed"),
        runtime.tool_call_id,
        agent_id,
        result.total,
    )
    return result.model_dump()


@tool(
    args_schema=ConversationSearchArgs,
    description=t("tools.memory.conversation_search.description"),
)
async def tdai_conversation_search(
    query: str,
    runtime: ToolRuntime,
    current_session_only: bool,
    top_k: int = 5,
    strategy: Literal["keyword", "embedding"] = "keyword",
) -> dict[str, Any]:
    """Search raw TDAI conversation records for the configured agent."""
    agent_id = _agent_id_from_runtime(runtime)
    resolved_session_key = (
        _thread_id_from_runtime(runtime) if current_session_only else None
    )
    logger.info(
        t("tools.memory.conversation_search.started"),
        runtime.tool_call_id,
        agent_id,
        resolved_session_key,
    )
    result = await MemoryManager.instance().search_conversations(
        agent_id=agent_id,
        query=query,
        top_k=top_k,
        strategy=strategy,
        session_key=resolved_session_key,
    )
    logger.info(
        t("tools.memory.conversation_search.completed"),
        runtime.tool_call_id,
        agent_id,
        result.total,
    )
    return result.model_dump()


def _agent_id_from_runtime(runtime: ToolRuntime) -> str:
    agent_id = _configurable(runtime).get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError(t("tools.memory.missing_agent_id"))
    return agent_id


def _thread_id_from_runtime(runtime: ToolRuntime) -> str | None:
    thread_id = _configurable(runtime).get("thread_id")
    return thread_id if isinstance(thread_id, str) and thread_id.strip() else None


def _configurable(runtime: ToolRuntime) -> dict[str, Any]:
    return runtime.config.get("configurable", {}) if runtime.config else {}


MemoryTools = [tdai_memory_search, tdai_conversation_search]
