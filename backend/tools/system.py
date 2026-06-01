import logging
import uuid
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field

from backend.dao.assigned_task import AssignedTaskDAO
from backend.db.session import async_session_factory
from backend.dto.assigned_task import AssignedTaskCreate
from backend.i18n import t

logger = logging.getLogger(__name__)


class AssignTaskArgs(BaseModel):
    task_name: str = Field(
        description=t("tools.system.assign_task.task_name.description")
    )
    goal: str = Field(description=t("tools.system.assign_task.goal.description"))


def _new_external_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def _configurable(runtime: ToolRuntime) -> dict[str, Any]:
    config = runtime.config or {}
    configurable = config.get("configurable")
    if isinstance(configurable, dict):
        return configurable
    return {}


def _required_int(configurable: dict[str, Any], key: str, error_key: str) -> int:
    value = configurable.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(t(error_key))


@tool(args_schema=AssignTaskArgs, description=t("tools.system.assign_task.description"))
async def assign_task(
    task_name: str, goal: str, runtime: ToolRuntime
) -> dict[str, Any]:
    task_name = task_name.strip()
    goal = goal.strip()
    if not task_name:
        return {
            "accepted": False,
            "error": t("tools.system.assign_task.blank_task_name"),
        }
    if not goal:
        return {"accepted": False, "error": t("tools.system.assign_task.blank_goal")}

    configurable = _configurable(runtime)
    user_db_id = _required_int(
        configurable,
        "user_db_id",
        "tools.system.assign_task.missing_runtime_user_id",
    )
    agent_db_id = _required_int(
        configurable,
        "agent_db_id",
        "tools.system.assign_task.missing_runtime_agent_id",
    )
    task_id = _new_external_id("task-")
    step_ids = (
        _new_external_id("task_step-"),
        _new_external_id("task_step-"),
        _new_external_id("task_step-"),
    )

    logger.info(
        t("tools.system.assign_task.started"),
        task_id,
        task_name,
        user_db_id,
        agent_db_id,
    )
    async with async_session_factory() as session:
        dao = AssignedTaskDAO(session)
        task_row = await dao.create(
            AssignedTaskCreate(
                task_id=task_id,
                user_id=user_db_id,
                responsible_agent_id=agent_db_id,
                task_name=task_name,
                goal=goal,
            )
        )
        step_rows = await dao.create_initial_steps(
            task_db_id=task_row.id,
            assign_agent_id=agent_db_id,
            step_ids=step_ids,
        )
        await session.commit()

    logger.info(t("tools.system.assign_task.completed"), task_id, task_name)
    return {
        "accepted": True,
        "task_id": task_id,
        "task_name": task_name,
        "status": "brainstorm_pending",
        "steps": [
            {
                "step_id": step.step_id,
                "title": step.title,
                "status": step.status,
            }
            for step in step_rows
        ],
    }


SystemTools = [assign_task]
