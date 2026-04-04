# pyright: reportMissingImports=false
"""
Dynamic LangChain tool loader from DB tool registry.

Converts DB tool definitions (name, description, JSON Schema) into
LangChain StructuredTool objects that can be bound to LLM nodes.

Usage:
    from tools.tools import get_tools

    tools = await get_tools(agent_db_id)
    llm_with_tools = llm.bind_tools(tools)
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from typing import Any, Callable, List, Optional
from uuid import UUID

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_tool_dao import AgentInstanceToolDAO
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from i18n import _

logger = logging.getLogger(__name__)

# JSON Schema type → Python type
_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _build_args_schema(tool_name: str, input_schema: dict[str, Any] | None) -> type[BaseModel]:
    """Convert a JSON Schema object into a Pydantic model for StructuredTool.

    Args:
        tool_name: Used as the model class name prefix.
        input_schema: JSON Schema dict (``{"type": "object", "properties": {...}}``)
            or None for tools that take no arguments.

    Returns:
        A dynamically created Pydantic BaseModel subclass.
    """
    if not input_schema or not input_schema.get("properties"):
        return create_model(f"{tool_name}Args")

    required: set[str] = set(input_schema.get("required", []))
    fields: dict[str, Any] = {}

    for prop_name, prop in input_schema["properties"].items():
        py_type = _JSON_TYPE_MAP.get(prop.get("type", "string"), str)
        desc = prop.get("description", "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=desc))
        else:
            default = prop.get("default", None)
            fields[prop_name] = (Optional[py_type], Field(default=default, description=desc))

    return create_model(f"{tool_name}Args", **fields)


def _make_executor(
    implementation_ref: str,
    merged_config: dict[str, Any],
    agent_db_id: str = "",
) -> Callable:
    """Build an async executor function for a tool.

    Dynamically imports ``module.path:function_name`` at call time so that
    new tools registered in the DB do not require a server restart.

    The wrapped function receives the tool arguments as keyword arguments plus
    ``_config`` containing the merged tool + instance configuration (which
    includes ``user_id`` for path security validation).
    If the target function accepts ``agent_db_id``, it is injected automatically.

    Args:
        implementation_ref: ``"module.path:function_name"`` string.
        merged_config: Tool-level config_json merged with instance config_override
            (instance values take precedence). Contains ``user_id`` for path security.
        agent_db_id: Agent instance UUID to inject into tools that accept it.

    Returns:
        An async coroutine function suitable for ``StructuredTool.from_function``.
    """
    module_path, func_name = implementation_ref.rsplit(":", 1)

    async def _arun(**kwargs: Any) -> str:
        module = importlib.import_module(module_path)
        fn = getattr(module, func_name)
        sig = inspect.signature(fn)
        if agent_db_id and "agent_db_id" in sig.parameters:
            kwargs.setdefault("agent_db_id", agent_db_id)
        if "_config" in sig.parameters:
            kwargs["_config"] = merged_config
        result = fn(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)

    return _arun


async def get_tools(agent_db_id: str) -> List[StructuredTool]:
    """Load and return all effective LangChain tools for an agent instance.

    Resolves the two-layer tool grant system (type-level + instance overrides),
    fetches each tool's default version from the registry, dynamically builds
    Pydantic arg schemas from JSON Schema, and wraps everything in
    ``StructuredTool``.

    Args:
        agent_db_id: The agent instance UUID string (as stored in DB /
            injected via ``config["configurable"]["agent_db_id"]``).

    Returns:
        List of ``StructuredTool`` objects ready for ``llm.bind_tools()``.
        Tools without a default version or ``implementation_ref`` are skipped.
    """
    instance_id = UUID(agent_db_id)

    # Fetch the agent instance to get user_id for path security
    agent_instance = await AgentInstanceDAO.get_by_id(instance_id)
    user_id = str(agent_instance.user_id) if agent_instance else ""

    tool_ids = await AgentInstanceToolDAO.get_effective_tools(instance_id)
    overrides = await AgentInstanceToolDAO.get_overrides_for_instance(instance_id)
    override_map: dict[UUID, dict[str, Any]] = {
        o.tool_id: (o.config_override or {}) for o in overrides
    }

    tools: List[StructuredTool] = []

    for tool_id in tool_ids:
        tool_dto = await ToolDAO.get_by_id(tool_id)
        if not tool_dto or not tool_dto.is_active:
            continue

        version = await ToolVersionDAO.get_default_version(tool_id)
        if not version or not version.implementation_ref:
            logger.warning(
                _("⚠️ 工具 %s 冇 default version 或 implementation_ref，跳過"),
                tool_dto.name,
            )
            continue

        # Merge config and inject user_id for path security
        merged_config: dict[str, Any] = {
            **(version.config_json or {}),
            **override_map.get(tool_id, {}),
            "user_id": user_id,  # Inject user_id for path security in system tools
            "agent_db_id": agent_db_id,
            "sandbox_scope": "session",
            "sandbox_scope_key": agent_db_id,
        }
        args_schema = _build_args_schema(tool_dto.name, version.input_schema)
        executor = _make_executor(version.implementation_ref, merged_config, agent_db_id)

        structured_tool = StructuredTool.from_function(
            coroutine=executor,
            name=tool_dto.name,
            description=tool_dto.description or tool_dto.name,
            args_schema=args_schema,
        )
        tools.append(structured_tool)
        logger.debug(
            _("✅ 已載入工具: %s (v%s) - %s"),
            tool_dto.name,
            version.version,
            tool_dto.description[:80] if tool_dto.description else "無描述",
        )

    logger.info(_("🔧 共載入 %s 個工具，agent_db_id: %s"), len(tools), agent_db_id)

    # Log tool names for debugging
    if tools:
        tool_names = [t.name for t in tools]
        logger.info(_("📋 可用工具列表: %s"), ", ".join(tool_names))
    else:
        logger.warning(_("⚠️ 沒有載入任何工具！"))

    return tools
