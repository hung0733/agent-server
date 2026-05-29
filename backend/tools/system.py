import json
import logging
from typing import Any, Sequence

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from backend.i18n import t

logger = logging.getLogger(__name__)

AssignTaskResult = dict[str, int | bool | str | list[str] | None]


class AssignTaskArgs(BaseModel):
    task_json: str = Field(
        description=t("tools.system.assign_task.task_json.description")
    )


@tool(
    args_schema=AssignTaskArgs,
    description=t("tools.system.assign_task.description"),
)
def assign_task(
    task_json: str, runtime: ToolRuntime
) -> AssignTaskResult:
    """Record an assigned task JSON payload."""
    allowed_agent_names = _allowed_agent_names_from_runtime(runtime)
    validation_error = validate_assign_task_payload(task_json, allowed_agent_names)
    logger.info(
        t("tools.system.assign_task.received"),
        runtime.tool_call_id,
        len(task_json),
        task_json,
    )
    if validation_error:
        logger.info(
            t("tools.system.assign_task.rejected"),
            runtime.tool_call_id,
            validation_error["error"],
        )
        return {
            "accepted": False,
            "length": len(task_json),
            "tool_call_id": runtime.tool_call_id,
            **validation_error,
        }

    return {
        "accepted": True,
        "length": len(task_json),
        "tool_call_id": runtime.tool_call_id,
    }


def validate_assign_task_payload(
    task_json: str, allowed_agent_names: Sequence[str]
) -> dict[str, str | list[str]] | None:
    try:
        payload = json.loads(task_json)
    except json.JSONDecodeError:
        return {"error": t("tools.system.assign_task.invalid_json")}

    if not isinstance(payload, dict):
        return {"error": t("tools.system.assign_task.invalid_object")}

    missing_fields = [
        field
        for field in ("state", "agent", "mission")
        if not _has_non_empty_string(payload.get(field))
    ]
    if missing_fields:
        return {
            "error": t("tools.system.assign_task.missing_required_fields"),
            "missing_fields": missing_fields,
        }

    agent_name = str(payload["agent"]).strip()
    if agent_name not in allowed_agent_names:
        return {
            "error": t("tools.system.assign_task.invalid_agent"),
            "invalid_agent": agent_name,
            "available_agents": list(allowed_agent_names),
        }

    return None


def _has_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _allowed_agent_names_from_runtime(runtime: ToolRuntime) -> list[str]:
    configurable = runtime.config.get("configurable", {}) if runtime.config else {}
    names = configurable.get("assign_task_allowed_agent_names", [])
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str) and name.strip()]


SystemTools = [assign_task]
