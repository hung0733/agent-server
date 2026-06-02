from __future__ import annotations

import logging

from backend.i18n import t
from backend.queues.task_queue import TaskQueueHandlerResult, TaskQueueStep

logger = logging.getLogger(__name__)


async def handle_assigned_task_step(task: TaskQueueStep) -> TaskQueueHandlerResult:
    logger.info(
        t("queues.task_queue_handle.started"),
        task.step_id,
        task.task_id,
        task.responsible_agent_id,
        task.agent_type,
    )
    log = t("queues.task_queue_handle.scaffold_completed") % task.step_id
    logger.info(t("queues.task_queue_handle.completed"), task.step_id, task.task_id)
    return TaskQueueHandlerResult(success=True, log=log)
