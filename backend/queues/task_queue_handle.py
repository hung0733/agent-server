from __future__ import annotations

import logging
from typing import AsyncGenerator
import uuid

from backend.agent.agent import Agent
from backend.dao.agent import AgentDAO
from backend.dao.agent_msg_hist import AgentMsgHistDAO
from backend.dao.assigned_task import AssignedTaskDAO
from backend.dao.session import AgentSessionDAO
from backend.db.session import async_session_factory
from backend.dto.session import AgentSessionCreate
from backend.i18n import t
from backend.queues.task_queue import (
    TaskQueueHandlerResult,
    TaskQueueStep,
    TaskQueueStepStatus,
)
from backend.sandbox.manager import get_agent_sandbox

logger = logging.getLogger(__name__)


async def handle_assigned_task_init_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    _log_started(task)

    async with async_session_factory() as session:
        agent_dao = AgentDAO(session)
        task_dao = AssignedTaskDAO(session)
        session_dao = AgentSessionDAO(session)

        assign_agent_db_id = task.assign_agent_db_id
        if task.assign_agent_id is None:
            logger.info(t("queues.task_queue_handle.find_assign_agent"), task.step_id)
            if task.user_db_id is None or task.agent_type_db_id is None:
                raise LookupError(
                    t("queues.task_queue_handle.sub_agent_not_found")
                    % (task.step_id, task.agent_type)
                )
            assign_agent = await agent_dao.get_first_active_sub_agent_by_user_and_type(
                user_id=task.user_db_id,
                agent_type_id=task.agent_type_db_id,
            )
            if assign_agent is None:
                raise LookupError(
                    t("queues.task_queue_handle.sub_agent_not_found")
                    % (task.step_id, task.agent_type)
                )
            assign_agent_db_id = assign_agent.id
            task.assign_agent_db_id = assign_agent.id
            task.assign_agent_id = assign_agent.agent_id
            await task_dao.update_step_assignment_and_session(
                step_db_id=task.step_db_id,
                assign_agent_db_id=assign_agent.id,
            )
        elif assign_agent_db_id is None:
            assign_agent = await agent_dao.get_by_agent_id(task.assign_agent_id)
            if assign_agent is None:
                raise LookupError(
                    t("queues.task_queue_handle.sub_agent_not_found")
                    % (task.step_id, task.agent_type)
                )
            assign_agent_db_id = assign_agent.id
            task.assign_agent_db_id = assign_agent.id

        if not task.task_session_id:
            logger.info(t("queues.task_queue_handle.find_task_session"), task.step_id)
            if task.responsible_agent_db_id is None:
                raise LookupError(
                    t("queues.task_queue_handle.default_session_not_found")
                    % (task.step_id, task.responsible_agent_id)
                )
            task_session = await session_dao.get_default_session_by_agent_db_id(
                task.responsible_agent_db_id
            )
            if task_session is None:
                raise LookupError(
                    t("queues.task_queue_handle.default_session_not_found")
                    % (task.step_id, task.responsible_agent_id)
                )
            task.task_session_id = task_session.session_id
            await task_dao.update_task_session(
                task_db_id=task.task_db_id,
                session_db_id=task_session.id,
            )

        if not task.step_session_id:
            logger.info(t("queues.task_queue_handle.find_step_session"), task.step_id)
            if assign_agent_db_id is None or task.responsible_agent_db_id is None:
                raise LookupError(
                    t("queues.task_queue_handle.sub_agent_not_found")
                    % (task.step_id, task.agent_type)
                )
            step_session_id = f"session-{uuid.uuid4()}"
            session_name = t("queues.task_queue_handle.step_session_name") % (
                task.task_create_dt.strftime("%Y%m%d"),
                task.title,
            )
            step_session = await session_dao.create(
                AgentSessionCreate(
                    recv_agent_id=assign_agent_db_id,
                    session_id=step_session_id,
                    name=session_name,
                    session_type="chat",
                    sender_agent_id=task.responsible_agent_db_id,
                )
            )
            task.step_session_id = step_session.session_id
            await task_dao.update_step_assignment_and_session(
                step_db_id=task.step_db_id,
                session_db_id=step_session.id,
            )

        await session.commit()

    task.change_status(TaskQueueStepStatus.INIT_MESSAGE)
    return None


async def handle_assigned_task_init_message_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    _log_started(task)
    async with async_session_factory() as session:
        step_session = await AgentSessionDAO(session).get_by_session_id(
            str(task.step_session_id or "")
        )
        if step_session is None:
            raise LookupError(
                t("queues.task_queue_handle.step_session_not_found")
                % (task.step_id, task.step_session_id)
            )

        history_count = await AgentMsgHistDAO(session).count_by_session_id(
            step_session.id
        )

    if history_count == 0:
        task.message = t("queues.task_queue_handle.initial_sub_agent_message") % (
            task.task_name,
            task.task_goal,
            task.goal,
        )
    else:
        task.message = t("queues.task_queue_handle.continue_sub_agent_message")

    task.change_status(TaskQueueStepStatus.SEND)
    return None


async def handle_assigned_task_send_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    _log_started(task)

    agent = await Agent.get_agent(str(task.assign_agent_id), str(task.step_session_id))
    sandbox = await get_agent_sandbox(agent.agent_id, agent.user_id)

    gen: AsyncGenerator = agent.send(
        task.message,
        think_mode=False,
        metadata={},
        sandbox=sandbox,
    )

    resp_message: str = ""
    is_interrupt: bool = False
    async for chunk in gen:
        if chunk.chunk_type == "content":
            resp_message += chunk.content or ""
        elif chunk.chunk_type == "interrupt":
            is_interrupt = True

    if is_interrupt:
        task.change_status(TaskQueueStepStatus.INTERRUPT)
    elif resp_message:
        task.message = resp_message
        task.change_status(TaskQueueStepStatus.RESPONSE)
    else:
        return _complete_scaffold_task(task)
    return None


async def handle_assigned_task_response_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    _log_started(task)
    return _complete_scaffold_task(task)


async def handle_assigned_task_resume_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    _log_started(task)
    return _complete_scaffold_task(task)


def _log_started(task: TaskQueueStep) -> None:
    logger.info(
        t("queues.task_queue_handle.started"),
        task.status,
        task.responsible_agent_id,
        task.assign_agent_id,
        task.task_session_id,
        task.step_session_id,
        task.task_name,
        task.title,
        task.step_id,
        task.task_id,
        task.agent_type,
    )


def _complete_scaffold_task(task: TaskQueueStep) -> TaskQueueHandlerResult:
    log = t("queues.task_queue_handle.scaffold_completed") % task.step_id
    task.change_status(TaskQueueStepStatus.COMPLETED)
    logger.info(t("queues.task_queue_handle.completed"), task.step_id, task.task_id)
    return TaskQueueHandlerResult(success=True, log=log)
