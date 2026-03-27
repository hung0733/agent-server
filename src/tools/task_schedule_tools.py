# pyright: reportMissingImports=false
"""
Scheduled task management tools for agents.

Provides async functions for agents to create and manage their own scheduled tasks:
- create_scheduled_task_impl: Create a new scheduled message task
- list_my_scheduled_tasks_impl: List the agent's scheduled tasks
- update_my_scheduled_task_impl: Update a scheduled task (prompt, schedule, status)
- delete_my_scheduled_task_impl: Delete a scheduled task

All tools are agent-scoped (can only manage own tasks).

These are raw async functions (not @tool decorated) that are wrapped into StructuredTools
by tools.py with agent_db_id injection.

Import path: tools.task_schedule_tools
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dto.task_dto import TaskCreate, TaskUpdate
from db.dto.task_schedule_dto import TaskScheduleCreate, TaskScheduleUpdate
from db.types import TaskStatus, Priority, ScheduleType
from i18n import _
from scheduler.task_scheduler import calculate_next_run, now_utc

logger = logging.getLogger(__name__)


async def create_scheduled_task_impl(
    prompt: str,
    schedule_expression: str,
    schedule_type: str = "cron",
    task_name: str = "",
    agent_db_id: str = "",
) -> str:
    """
    Create a new scheduled task for the agent.

    The task will automatically run at the specified schedule, sending the prompt
    to simulate a user message.

    Args:
        prompt: The prompt/message to send to the agent when scheduled.
        schedule_expression: Schedule definition (format depends on type):
            - cron: "0 12 * * *" (noon daily)
            - interval: "PT1H" (every hour), "P1D" (daily), "P1W" (weekly)
            - once: "2026-03-26T12:00:00Z" (one-time execution)
        schedule_type: Type of schedule - "cron", "interval", or "once"
            Defaults to "cron"
        task_name: Optional human-readable name for the task
        agent_db_id: Agent instance UUID (auto-injected)

    Returns:
        Success message with task and schedule IDs

    Raises:
        ValueError: If inputs are invalid or task creation fails
    """
    try:
        if not agent_db_id:
            return _(
                "❌ 無法獲取 agent_db_id。"
                "此工具只能在 agent 上下文中使用。"
            )

        logger.info(
            _(
                "[create_scheduled_task] 創建排程任務: agent_db_id=%s, schedule_type=%s"
            ),
            agent_db_id,
            schedule_type,
        )

        # 1. Validate inputs
        if not prompt or not prompt.strip():
            raise ValueError(_("prompt 不能為空"))

        if not schedule_expression or not schedule_expression.strip():
            raise ValueError(_("schedule_expression 不能為空"))

        try:
            sched_type = ScheduleType(schedule_type)
        except ValueError:
            raise ValueError(
                _(
                    "無效的 schedule_type: %s (有效值: cron, interval, once)"
                )
                % schedule_type
            )

        # 2. Get agent instance to verify it exists
        agent_instance = await AgentInstanceDAO.get_by_id(UUID(agent_db_id))
        if not agent_instance:
            raise ValueError(
                _(
                    "Agent instance 不存在: %s"
                )
                % agent_db_id
            )

        logger.debug(_("[create_scheduled_task] ✅ Agent 驗證通過: %s"), agent_instance.name)

        # 3. Calculate next run time
        next_run = calculate_next_run(schedule_expression, sched_type)
        logger.debug(
            _("[create_scheduled_task] 計算 next_run: %s"),
            next_run.isoformat() if next_run else "None",
        )

        # 4. Create task
        task = await TaskDAO.create(
            TaskCreate(
                user_id=agent_instance.user_id,
                agent_id=agent_instance.id,
                task_type="scheduled_message",
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={
                    "task_execution_type": "message",
                    "prompt": prompt,
                    "system_prompt": "",
                    "think_mode": False,
                    "name": task_name or "Scheduled Task",
                },
            )
        )
        logger.debug(_("[create_scheduled_task] ✅ Task 創建成功: %s"), task.id)

        # 5. Create schedule
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=sched_type,
                schedule_expression=schedule_expression,
                is_active=True,
                next_run_at=next_run,
            )
        )
        logger.debug(_("[create_scheduled_task] ✅ Schedule 創建成功: %s"), schedule.id)

        return _(
            "✅ 排程任務已創建！\n"
            "任務 ID: %s\n"
            "排程 ID: %s\n"
            "排程類型: %s\n"
            "下次執行: %s"
        ) % (
            task.id,
            schedule.id,
            schedule_type,
            next_run.isoformat() if next_run else _("一次性任務（已執行後不再重複）"),
        )

    except Exception as e:
        logger.error(
            _("[create_scheduled_task] ❌ 建立失敗: %s"),
            str(e),
            exc_info=True,
        )
        return _(
            "❌ 建立排程任務失敗: %s"
        ) % str(e)


async def list_my_scheduled_tasks_impl(
    agent_db_id: str = "",
) -> str:
    """
    List all scheduled tasks for the agent.

    Shows task name, schedule type, expression, and next run time.

    Args:
        agent_db_id: Agent instance UUID (auto-injected)

    Returns:
        Formatted list of scheduled tasks
    """
    try:
        if not agent_db_id:
            return _(
                "❌ 無法獲取 agent_db_id。"
                "此工具只能在 agent 上下文中使用。"
            )

        logger.info(
            _("[list_my_scheduled_tasks] 列出排程任務: agent_db_id=%s"),
            agent_db_id,
        )

        # 1. Get all tasks for this agent
        tasks = await TaskDAO.get_by_agent_id(UUID(agent_db_id), limit=100)
        logger.debug(
            _("[list_my_scheduled_tasks] 找到 %d 個任務"),
            len(tasks),
        )

        if not tasks:
            return _(
                "📭 此 agent 尚未有任何排程任務"
            )

        # 2. Get schedules for each task
        result_lines = [_(
            "📋 此 Agent 的排程任務\n"
            "="
        )]

        for task in tasks:
            # Only show scheduled message tasks
            if task.payload and task.payload.get("task_execution_type") != "message":
                continue

            schedule = await TaskScheduleDAO.get_by_task_template_id(task.id)
            if not schedule:
                continue

            task_name = (
                task.payload.get("name", "Unnamed Task")
                if task.payload
                else "Unnamed Task"
            )
            prompt_preview = (
                task.payload.get("prompt", "")[:50]
                if task.payload
                else ""
            )

            status = "✅ 啟用" if schedule.is_active else "❌ 停用"
            next_run = (
                schedule.next_run_at.isoformat()
                if schedule.next_run_at
                else _("一次性任務")
            )

            result_lines.append("")
            result_lines.append(
                _(
                    "📌 %s"
                ) % task_name
            )
            result_lines.append(
                _(
                    "   ID: %s"
                ) % task.id
            )
            result_lines.append(
                _(
                    "   排程: %s - %s"
                ) % (schedule.schedule_type, schedule.schedule_expression)
            )
            result_lines.append(
                _(
                    "   提示詞: %s..."
                ) % prompt_preview
            )
            result_lines.append(
                _(
                    "   狀態: %s"
                ) % status
            )
            result_lines.append(
                _(
                    "   下次執行: %s"
                ) % next_run
            )

        return "\n".join(result_lines)

    except Exception as e:
        logger.error(
            _("[list_my_scheduled_tasks] ❌ 列表查詢失敗: %s"),
            str(e),
            exc_info=True,
        )
        return _(
            "❌ 列表查詢失敗: %s"
        ) % str(e)


async def update_my_scheduled_task_impl(
    task_id: str,
    prompt: str = None,
    schedule_expression: str = None,
    is_active: bool = None,
    agent_db_id: str = "",
) -> str:
    """
    Update a scheduled task.

    Can update the prompt, schedule, or enable/disable the task.

    Args:
        task_id: ID of the task to update
        prompt: New prompt (optional)
        schedule_expression: New schedule expression (optional)
        is_active: Enable/disable the task (optional)
        agent_db_id: Agent instance UUID (auto-injected)

    Returns:
        Success or error message
    """
    try:
        if not agent_db_id:
            return _(
                "❌ 無法獲取 agent_db_id。"
                "此工具只能在 agent 上下文中使用。"
            )

        logger.info(
            _(
                "[update_my_scheduled_task] 更新任務: task_id=%s, agent_db_id=%s"
            ),
            task_id,
            agent_db_id,
        )

        # 1. Get the task
        task = await TaskDAO.get_by_id(UUID(task_id))
        if not task:
            raise ValueError(
                _(
                    "任務不存在: %s"
                ) % task_id
            )

        # 2. Verify ownership
        if str(task.agent_id) != agent_db_id:
            raise ValueError(
                _(
                    "無權限修改此任務（不是 agent 的任務）"
                )
            )

        logger.debug(_("[update_my_scheduled_task] ✅ 任務驗證通過"))

        # 3. Update task payload if prompt provided
        if prompt:
            if not task.payload:
                task.payload = {}
            task.payload["prompt"] = prompt

        # 4. Update schedule if expression provided
        if schedule_expression:
            schedule = await TaskScheduleDAO.get_by_task_template_id(task.id)
            if not schedule:
                raise ValueError(
                    _(
                        "任務沒有關聯的排程"
                    )
                )

            # Recalculate next_run
            next_run = calculate_next_run(
                schedule_expression,
                schedule.schedule_type,
                now_utc(),
            )

            await TaskScheduleDAO.update(
                TaskScheduleUpdate(
                    id=schedule.id,
                    schedule_expression=schedule_expression,
                    next_run_at=next_run,
                )
            )
            logger.debug(_("[update_my_scheduled_task] ✅ 排程已更新"))

        # 5. Update active status if provided
        if is_active is not None:
            schedule = await TaskScheduleDAO.get_by_task_template_id(task.id)
            if schedule:
                await TaskScheduleDAO.update(
                    TaskScheduleUpdate(
                        id=schedule.id,
                        is_active=is_active,
                    )
                )
                logger.debug(
                    _("[update_my_scheduled_task] ✅ 狀態已更新: %s"),
                    "啟用" if is_active else "停用",
                )

        # 6. Update task with new payload
        await TaskDAO.update(
            TaskUpdate(
                id=task.id,
                payload=task.payload,
            )
        )

        return _(
            "✅ 排程任務已更新！\n"
            "任務 ID: %s"
        ) % task.id

    except Exception as e:
        logger.error(
            _("[update_my_scheduled_task] ❌ 更新失敗: %s"),
            str(e),
            exc_info=True,
        )
        return _(
            "❌ 更新排程任務失敗: %s"
        ) % str(e)


async def delete_my_scheduled_task_impl(
    task_id: str,
    agent_db_id: str = "",
) -> str:
    """
    Delete a scheduled task.

    Args:
        task_id: ID of the task to delete
        agent_db_id: Agent instance UUID (auto-injected)

    Returns:
        Success or error message
    """
    try:
        if not agent_db_id:
            return _(
                "❌ 無法獲取 agent_db_id。"
                "此工具只能在 agent 上下文中使用。"
            )

        logger.info(
            _(
                "[delete_my_scheduled_task] 刪除任務: task_id=%s, agent_db_id=%s"
            ),
            task_id,
            agent_db_id,
        )

        # 1. Get the task
        task = await TaskDAO.get_by_id(UUID(task_id))
        if not task:
            raise ValueError(
                _(
                    "任務不存在: %s"
                ) % task_id
            )

        # 2. Verify ownership
        if str(task.agent_id) != agent_db_id:
            raise ValueError(
                _(
                    "無權限刪除此任務（不是 agent 的任務）"
                )
            )

        logger.debug(_("[delete_my_scheduled_task] ✅ 任務驗證通過"))

        # 3. Delete the task (cascade will delete schedule)
        success = await TaskDAO.delete(UUID(task_id))

        if success:
            logger.debug(_("[delete_my_scheduled_task] ✅ 任務已刪除"))
            return _(
                "✅ 排程任務已刪除！\n"
                "任務 ID: %s"
            ) % task_id
        else:
            return _(
                "❌ 任務刪除失敗"
            )

    except Exception as e:
        logger.error(
            _("[delete_my_scheduled_task] ❌ 刪除失敗: %s"),
            str(e),
            exc_info=True,
        )
        return _(
            "❌ 刪除排程任務失敗: %s"
        ) % str(e)


# =============================================================================
# Factory Functions - Create agent-specific tool functions
# =============================================================================
# These factories create functions with the correct signature that Pydantic
# can inspect, with agent_db_id already bound in the closure.


def create_scheduled_task_for_agent(agent_db_id: str):
    """Factory to create create_scheduled_task function with agent_db_id bound."""
    async def create_scheduled_task(
        prompt: str,
        schedule_expression: str,
        schedule_type: str = "cron",
        task_name: str = "",
    ) -> str:
        return await create_scheduled_task_impl(
            prompt=prompt,
            schedule_expression=schedule_expression,
            schedule_type=schedule_type,
            task_name=task_name,
            agent_db_id=agent_db_id,
        )
    return create_scheduled_task


def list_my_scheduled_tasks_for_agent(agent_db_id: str):
    """Factory to create list_my_scheduled_tasks function with agent_db_id bound."""
    async def list_my_scheduled_tasks() -> str:
        return await list_my_scheduled_tasks_impl(agent_db_id=agent_db_id)
    return list_my_scheduled_tasks


def update_my_scheduled_task_for_agent(agent_db_id: str):
    """Factory to create update_my_scheduled_task function with agent_db_id bound."""
    async def update_my_scheduled_task(
        task_id: str,
        prompt: str = None,
        schedule_expression: str = None,
        is_active: bool = None,
    ) -> str:
        return await update_my_scheduled_task_impl(
            task_id=task_id,
            prompt=prompt,
            schedule_expression=schedule_expression,
            is_active=is_active,
            agent_db_id=agent_db_id,
        )
    return update_my_scheduled_task


def delete_my_scheduled_task_for_agent(agent_db_id: str):
    """Factory to create delete_my_scheduled_task function with agent_db_id bound."""
    async def delete_my_scheduled_task(task_id: str) -> str:
        return await delete_my_scheduled_task_impl(
            task_id=task_id,
            agent_db_id=agent_db_id,
        )
    return delete_my_scheduled_task
