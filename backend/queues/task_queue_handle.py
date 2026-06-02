from __future__ import annotations

import logging

from backend.i18n import t
from backend.queues.task_queue import (
    TaskQueueHandlerResult,
    TaskQueueStep,
    TaskQueueStepStatus,
)

logger = logging.getLogger(__name__)


async def handle_assigned_task_init_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    logger.info(
        t("queues.task_queue_handle.started"),
        task.step_id,
        task.task_id,
        task.responsible_agent_id,
        task.agent_type,
    )
    task.change_status(TaskQueueStepStatus.SEND)
    return None


async def handle_assigned_task_send_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    logger.info(
        t("queues.task_queue_handle.started"),
        task.step_id,
        task.task_id,
        task.responsible_agent_id,
        task.agent_type,
    )
    return _complete_scaffold_task(task)


async def handle_assigned_task_resume_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    logger.info(
        t("queues.task_queue_handle.started"),
        task.step_id,
        task.task_id,
        task.responsible_agent_id,
        task.agent_type,
    )
    return _complete_scaffold_task(task)


def _complete_scaffold_task(task: TaskQueueStep) -> TaskQueueHandlerResult:
    log = t("queues.task_queue_handle.scaffold_completed") % task.step_id
    task.change_status(TaskQueueStepStatus.COMPLETED)
    logger.info(t("queues.task_queue_handle.completed"), task.step_id, task.task_id)
    return TaskQueueHandlerResult(success=True, log=log)
