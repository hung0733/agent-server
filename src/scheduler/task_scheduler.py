# pyright: reportMissingImports=false
"""
Task scheduler service for executing scheduled tasks.

Runs as a background service that:
1. Periodically scans for due scheduled tasks
2. Executes tasks and handles results
3. Calculates next run times for recurring schedules

Import path: scheduler.task_scheduler
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from croniter import croniter
from isodate import parse_duration

from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.task_queue_dao import TaskQueueDAO
from db.dao.task_dependency_dao import TaskDependencyDAO
from db.dto.task_schedule_dto import TaskScheduleUpdate
from db.dto.task_dto import TaskUpdate
from db.dto.task_queue_dto import TaskQueueCreate, TaskQueueUpdate
from db.types import TaskStatus, ScheduleType, TaskExecutionType, Priority
from i18n import _
from scheduler.task_executor import TaskExecutor

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def priority_to_int(priority: Priority | None) -> int:
    """
    Convert Priority enum to integer value for task queue.

    Args:
        priority: Priority enum value or None

    Returns:
        Integer priority (higher = more urgent)
        - critical: 30
        - high: 20
        - normal: 10
        - low: 0
        - None: 10 (default to normal)
    """
    if priority is None:
        return 10

    priority_map = {
        Priority.low: 0,
        Priority.normal: 10,
        Priority.high: 20,
        Priority.critical: 30,
    }

    return priority_map.get(priority, 10)


def calculate_retry_delay_seconds(consecutive_failures: int) -> int:
    """
    Calculate retry delay in seconds based on consecutive failure count.

    Implements exponential backoff strategy:
    - 1st failure: 30 seconds
    - 2nd consecutive failure: 60 seconds (1 minute)
    - 3rd consecutive failure: 300 seconds (5 minutes)
    - 4th consecutive failure: 900 seconds (15 minutes)
    - 5+ consecutive failures: 3600 seconds (60 minutes)

    Args:
        consecutive_failures: Number of consecutive execution failures

    Returns:
        Retry delay in seconds
    """
    if consecutive_failures == 0:
        # No failures, no delay
        return 0
    elif consecutive_failures == 1:
        # First failure: retry after 30 seconds
        return 30
    elif consecutive_failures == 2:
        # Second consecutive failure: retry after 60 seconds
        return 60
    elif consecutive_failures == 3:
        # Third consecutive failure: retry after 5 minutes
        return 300
    elif consecutive_failures == 4:
        # Fourth consecutive failure: retry after 15 minutes
        return 900
    else:
        # Fifth and subsequent consecutive failures: retry after 60 minutes
        return 3600


def calculate_next_run(
    schedule_expression: str,
    schedule_type: ScheduleType,
    base_time: Optional[datetime] = None,
) -> Optional[datetime]:
    """
    Calculate the next run time for a schedule.

    Args:
        schedule_expression: The schedule expression (format depends on type)
        schedule_type: Type of schedule (cron, interval, or once)
        base_time: Reference time to calculate from (defaults to now)

    Returns:
        datetime of next run, or None for one-time schedules after execution

    Raises:
        ValueError: If schedule_expression format is invalid
    """
    if base_time is None:
        base_time = now_utc()

    try:
        if schedule_type == ScheduleType.once:
            # One-time schedule: return None (won't run again)
            return None

        elif schedule_type == ScheduleType.cron:
            # Cron expression: use croniter to calculate next run
            # croniter expects cron expression without seconds
            # Format: minute hour day month weekday
            try:
                cron = croniter(schedule_expression, base_time)
                next_run = cron.get_next(datetime)
                logger.debug(
                    _(
                        "[calculate_next_run] cron='%s' @ %s -> next=%s"
                    ),
                    schedule_expression,
                    base_time.isoformat(),
                    next_run.isoformat() if next_run else None,
                )
                return next_run
            except Exception as e:
                raise ValueError(
                    _(
                        "無效的 cron 表達式 '%s': %s"
                    )
                    % (schedule_expression, str(e))
                )

        elif schedule_type == ScheduleType.interval:
            # ISO 8601 duration: parse and add to base time
            # Example: PT1H (1 hour), P1D (1 day), P1W (1 week)
            try:
                duration = parse_duration(schedule_expression)
                next_run = base_time + duration
                logger.debug(
                    _(
                        "[calculate_next_run] interval='%s' @ %s -> next=%s"
                    ),
                    schedule_expression,
                    base_time.isoformat(),
                    next_run.isoformat(),
                )
                return next_run
            except Exception as e:
                raise ValueError(
                    _(
                        "無效的 interval 表達式 '%s': %s"
                    )
                    % (schedule_expression, str(e))
                )

        else:
            raise ValueError(
                _(
                    "未知的 schedule_type: %s"
                )
                % schedule_type
            )

    except Exception as e:
        logger.error(
            _(
                "[calculate_next_run] 計算失敗: schedule_type=%s, expr=%s, error=%s"
            ),
            schedule_type,
            schedule_expression,
            str(e),
        )
        raise


class TaskScheduler:
    """
    Background service for executing scheduled tasks.

    Periodically scans for due tasks and executes them concurrently,
    then updates the next_run_at timestamp.

    Each task is executed in a separate asyncio task to avoid blocking
    the main scheduler loop.
    """

    def __init__(self):
        """Initialize the task scheduler."""
        self.running = False
        # Get interval from env (default 60 seconds)
        self.interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
        # Track active tasks for concurrent execution
        self.active_tasks: set[asyncio.Task] = set()
        logger.info(
            _(
                "[TaskScheduler] 初始化完成，掃描間隔: %d 秒"
            ),
            self.interval,
        )

    async def start(self) -> None:
        """
        Start the scheduler background loop.

        Runs continuously until stopped.
        """
        if self.running:
            logger.warning(_("[TaskScheduler] 已經在運行中"))
            return

        self.running = True
        logger.info(_("[TaskScheduler] ✅ 排程服務已啟動"))

        try:
            while self.running:
                try:
                    await self.tick()
                except Exception as e:
                    logger.error(
                        _("[TaskScheduler] 💥 掃描週期出錯: %s"),
                        str(e),
                        exc_info=True,
                    )
                    # Continue running even if one tick fails
                    pass

                # Sleep before next tick
                await asyncio.sleep(self.interval)

        except Exception as e:
            logger.error(
                _("[TaskScheduler] 致命錯誤，服務停止: %s"),
                str(e),
                exc_info=True,
            )
            self.running = False

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self.running:
            logger.warning(_("[TaskScheduler] 未在運行中"))
            return

        logger.info(_("[TaskScheduler] 正在關閉..."))
        self.running = False

        # Wait for all active tasks to complete
        if self.active_tasks:
            logger.info(
                _("[TaskScheduler] 等待 %d 個任務完成..."),
                len(self.active_tasks),
            )
            await asyncio.gather(*self.active_tasks, return_exceptions=True)

        logger.info(_("[TaskScheduler] ✅ 排程服務已關閉"))

    async def tick(self) -> None:
        """
        Single execution cycle.

        Scans for due tasks and executes them concurrently.
        """
        current_time = now_utc()
        logger.debug(_("[TaskScheduler.tick] 開始掃描，當前時間: %s"), current_time.isoformat())

        # Clean up completed tasks from active_tasks set
        done_tasks = {task for task in self.active_tasks if task.done()}
        self.active_tasks -= done_tasks

        logger.debug(
            _("[TaskScheduler.tick] 活動任務數: %d (清理 %d 個已完成)"),
            len(self.active_tasks),
            len(done_tasks),
        )

        try:
            # 1. Get all due schedules (next_run_at <= now)
            due_schedules = await TaskScheduleDAO.get_due_schedules(current_time)
            logger.debug(
                _(
                    "[TaskScheduler.tick] 找到 %d 個到期排程"
                ),
                len(due_schedules),
            )

            if not due_schedules:
                logger.debug(_("[TaskScheduler.tick] 無待執行任務"))
                return

            # 2. Launch each due schedule in a separate asyncio task (non-blocking)
            for schedule in due_schedules:
                try:
                    # Create a background task for concurrent execution
                    task = asyncio.create_task(
                        self._execute_schedule_wrapper(schedule, current_time)
                    )
                    self.active_tasks.add(task)
                    logger.debug(
                        _(
                            "[TaskScheduler.tick] 已啟動排程任務: schedule_id=%s"
                        ),
                        schedule.id,
                    )
                except Exception as e:
                    logger.error(
                        _(
                            "[TaskScheduler.tick] 啟動排程失敗 (schedule_id=%s): %s"
                        ),
                        schedule.id,
                        str(e),
                        exc_info=True,
                    )
                    # Continue with next schedule

        except Exception as e:
            logger.error(
                _("[TaskScheduler.tick] 掃描失敗: %s"),
                str(e),
                exc_info=True,
            )

    async def _execute_schedule_wrapper(self, schedule, current_time: datetime) -> None:
        """
        Wrapper for _execute_schedule that catches all exceptions.

        This prevents unhandled exceptions from crashing background tasks.
        """
        try:
            await self._execute_schedule(schedule, current_time)
        except Exception as e:
            logger.error(
                _(
                    "[TaskScheduler._execute_schedule_wrapper] 執行排程失敗 (schedule_id=%s): %s"
                ),
                schedule.id,
                str(e),
                exc_info=True,
            )

    async def _execute_schedule(self, schedule, current_time: datetime) -> None:
        """
        Execute a single schedule.

        Args:
            schedule: TaskSchedule DTO
            current_time: Current UTC datetime
        """
        logger.info(
            _(
                "[TaskScheduler._execute_schedule] 執行排程: id=%s, next_run_at=%s"
            ),
            schedule.id,
            schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        )

        # 1. Get the template task
        template_task = await TaskDAO.get_by_id(schedule.task_template_id)
        if not template_task:
            logger.error(
                _(
                    "[TaskScheduler._execute_schedule] 找不到模板任務: %s"
                ),
                schedule.task_template_id,
            )
            return

        logger.debug(
            _(
                "[TaskScheduler._execute_schedule] 模板任務: type=%s, agent_id=%s"
            ),
            template_task.task_type,
            template_task.agent_id,
        )

        # 2. Create execution instance (copy of template task)
        try:
            from db.dto.task_dto import TaskCreate
            from uuid import UUID

            execution_task = await TaskDAO.create(
                TaskCreate(
                    user_id=template_task.user_id,
                    agent_id=template_task.agent_id,
                    task_type=template_task.task_type,
                    status=TaskStatus.pending,
                    priority=template_task.priority,
                    payload=template_task.payload,
                    session_id=template_task.session_id,
                    parent_task_id=template_task.id,  # Link to template
                )
            )
            logger.debug(
                _(
                    "[TaskScheduler._execute_schedule] 創建執行實例: %s"
                ),
                execution_task.id,
            )

            # 2a. Check if dependencies are met
            can_run = await TaskDependencyDAO.are_dependencies_met(execution_task.id)
            if not can_run:
                logger.info(
                    _(
                        "[TaskScheduler._execute_schedule] 任務依賴未滿足，延遲執行: %s"
                    ),
                    execution_task.id,
                )
                # Update schedule to try again later (e.g., 5 minutes)
                from datetime import timedelta
                await TaskScheduleDAO.update(
                    TaskScheduleUpdate(
                        id=schedule.id,
                        next_run_at=current_time + timedelta(minutes=5),
                    )
                )
                return

            # 2b. Add to task queue
            queue_entry = await TaskQueueDAO.create(
                TaskQueueCreate(
                    task_id=execution_task.id,
                    status=TaskStatus.pending,
                    priority=priority_to_int(template_task.priority),
                    scheduled_at=current_time,
                )
            )
            logger.debug(
                _(
                    "[TaskScheduler._execute_schedule] 任務已加入隊列: queue_id=%s"
                ),
                queue_entry.id,
            )

        except Exception as e:
            logger.error(
                _(
                    "[TaskScheduler._execute_schedule] 創建執行實例失敗: %s"
                ),
                str(e),
                exc_info=True,
            )
            return

        # 3. Execute the task
        try:
            logger.debug(
                _(
                    "[TaskScheduler._execute_schedule] 開始執行任務: %s"
                ),
                execution_task.id,
            )

            # Update task and queue to running
            await TaskDAO.update(
                TaskUpdate(id=execution_task.id, status=TaskStatus.running)
            )
            await TaskQueueDAO.update(
                TaskQueueUpdate(
                    id=queue_entry.id,
                    status=TaskStatus.running,
                    started_at=current_time,
                )
            )

            # Execute (TaskExecutor will handle agent claim/release)
            result = await TaskExecutor.execute_task(execution_task)

            # Update task and queue to completed
            await TaskDAO.update(
                TaskUpdate(
                    id=execution_task.id,
                    status=TaskStatus.completed,
                    result=result,
                )
            )
            await TaskQueueDAO.update(
                TaskQueueUpdate(
                    id=queue_entry.id,
                    status=TaskStatus.completed,
                    completed_at=now_utc(),
                    result_json=result,
                )
            )

            logger.info(
                _(
                    "[TaskScheduler._execute_schedule] ✅ 任務執行成功: %s"
                ),
                execution_task.id,
            )

        except ValueError as e:
            # Handle agent not available (busy) - reschedule for later
            error_msg = str(e)
            if "不是 idle 狀態" in error_msg or "Agent" in error_msg:
                logger.warning(
                    _(
                        "[TaskScheduler._execute_schedule] Agent 忙碌，延遲重試: %s"
                    ),
                    error_msg,
                )

                # Update task to pending (not failed)
                await TaskDAO.update(
                    TaskUpdate(
                        id=execution_task.id,
                        status=TaskStatus.pending,
                        error_message=error_msg[:500],
                    )
                )
                await TaskQueueDAO.update(
                    TaskQueueUpdate(
                        id=queue_entry.id,
                        status=TaskStatus.pending,
                        error_message=error_msg[:500],
                    )
                )

                # Increment consecutive_failures and calculate retry delay
                from datetime import timedelta
                new_failure_count = schedule.consecutive_failures + 1
                retry_delay_seconds = calculate_retry_delay_seconds(new_failure_count)
                next_retry_time = current_time + timedelta(seconds=retry_delay_seconds)

                logger.info(
                    _(
                        "[TaskScheduler._execute_schedule] 連續失敗次數: %d，將於 %d 秒後重試 (時間: %s)"
                    ),
                    new_failure_count,
                    retry_delay_seconds,
                    next_retry_time.isoformat(),
                )

                await TaskScheduleDAO.update(
                    TaskScheduleUpdate(
                        id=schedule.id,
                        consecutive_failures=new_failure_count,
                        last_failure_at=current_time,
                        next_run_at=next_retry_time,
                    )
                )
                return  # Don't update last_run_at since we're rescheduling

            else:
                # Other ValueError - treat as failure
                raise

        except Exception as e:
            logger.error(
                _(
                    "[TaskScheduler._execute_schedule] 任務執行失敗: %s"
                ),
                str(e),
                exc_info=True,
            )

            # Update task and queue to failed
            await TaskDAO.update(
                TaskUpdate(
                    id=execution_task.id,
                    status=TaskStatus.failed,
                    error_message=str(e)[:500],  # Limit error message length
                )
            )
            await TaskQueueDAO.update(
                TaskQueueUpdate(
                    id=queue_entry.id,
                    status=TaskStatus.failed,
                    error_message=str(e)[:500],
                    completed_at=now_utc(),
                )
            )

            # Increment consecutive_failures and calculate retry delay
            from datetime import timedelta
            new_failure_count = schedule.consecutive_failures + 1
            retry_delay_seconds = calculate_retry_delay_seconds(new_failure_count)
            next_retry_time = current_time + timedelta(seconds=retry_delay_seconds)

            logger.info(
                _(
                    "[TaskScheduler._execute_schedule] 連續失敗次數: %d，將於 %d 秒後重試 (時間: %s)"
                ),
                new_failure_count,
                retry_delay_seconds,
                next_retry_time.isoformat(),
            )

            # Update schedule with failure info (don't update last_run_at - retry instead)
            await TaskScheduleDAO.update(
                TaskScheduleUpdate(
                    id=schedule.id,
                    consecutive_failures=new_failure_count,
                    last_failure_at=current_time,
                    next_run_at=next_retry_time,
                )
            )
            return  # Don't proceed to update last_run_at or calculate next regular run

        # 4. Update schedule's next_run_at (only reached if task succeeded)
        try:
            next_run = calculate_next_run(
                schedule.schedule_expression,
                schedule.schedule_type,
                current_time,
            )

            # Reset failure tracking on successful execution
            await TaskScheduleDAO.update(
                TaskScheduleUpdate(
                    id=schedule.id,
                    last_run_at=current_time,
                    next_run_at=next_run,
                    consecutive_failures=0,
                    last_failure_at=None,
                )
            )

            logger.debug(
                _(
                    "[TaskScheduler._execute_schedule] 排程已更新: next_run_at=%s"
                ),
                next_run.isoformat() if next_run else "None (one-time schedule)",
            )

        except Exception as e:
            logger.error(
                _(
                    "[TaskScheduler._execute_schedule] 更新排程失敗: %s"
                ),
                str(e),
                exc_info=True,
            )
