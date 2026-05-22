import logging

from pydantic import BaseModel, Field
from langchain.tools import ToolRuntime, tool

from backend.i18n import t

logger = logging.getLogger(__name__)


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
) -> dict[str, int | bool | str | None]:
    """Record an assigned task JSON payload."""
    logger.info(
        t("tools.system.assign_task.received"),
        runtime.tool_call_id,
        len(task_json),
        task_json,
    )
    return {
        "accepted": True,
        "length": len(task_json),
        "tool_call_id": runtime.tool_call_id,
    }


SystemTools = [assign_task]
