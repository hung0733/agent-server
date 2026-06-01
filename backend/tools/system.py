import logging
import uuid
from datetime import datetime, timedelta, timezone
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


class ListAssignedTasksArgs(BaseModel):
    pass


class ReadAssignedTaskArgs(BaseModel):
    task_id: str = Field(
        description=t("tools.system.read_assigned_task.task_id.description")
    )


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


def _task_dict(task: Any, *, include_steps: bool = False) -> dict[str, Any]:
    data = {
        "task_id": task.task_id,
        "task_name": task.task_name,
        "goal": task.goal,
        "status": task.status,
        "create_dt": _isoformat(task.create_dt),
        "update_dt": _isoformat(task.update_dt),
    }
    if hasattr(task, "approved_plan_html"):
        data["approved_plan_html"] = task.approved_plan_html
    if include_steps:
        steps = sorted(getattr(task, "steps", []), key=lambda step: step.seq_no)
        data["steps"] = [_step_dict(step) for step in steps]
    return data


def _step_dict(step: Any) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "step_type": step.step_type,
        "title": step.title,
        "goal": step.goal,
        "status": step.status,
        "seq_no": step.seq_no,
        "output_html": step.output_html,
        "output_json": step.output_json,
    }


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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


@tool(
    args_schema=ListAssignedTasksArgs,
    description=t("tools.system.list_assigned_tasks.description"),
)
async def list_assigned_tasks(runtime: ToolRuntime) -> dict[str, Any]:
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
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    async with async_session_factory() as session:
        dao = AssignedTaskDAO(session)
        tasks = await dao.list_open_and_recent_finished(
            user_id=user_db_id,
            agent_id=agent_db_id,
            since=since,
        )

    return {
        "accepted": True,
        "tasks": [_task_dict(task) for task in tasks],
    }


@tool(
    args_schema=ReadAssignedTaskArgs,
    description=t("tools.system.read_assigned_task.description"),
)
async def read_assigned_task(task_id: str, runtime: ToolRuntime) -> dict[str, Any]:
    task_id = task_id.strip()
    if not task_id:
        return {
            "accepted": False,
            "error": t("tools.system.read_assigned_task.blank_task_id"),
        }

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

    async with async_session_factory() as session:
        dao = AssignedTaskDAO(session)
        task_row = await dao.get_detail_by_task_id(
            user_id=user_db_id,
            agent_id=agent_db_id,
            task_id=task_id,
        )

    if not task_row:
        return {
            "accepted": False,
            "error": t("tools.system.read_assigned_task.not_found"),
        }

    return {
        "accepted": True,
        "task": _task_dict(task_row, include_steps=True),
    }


SystemTools = [assign_task, list_assigned_tasks, read_assigned_task]
