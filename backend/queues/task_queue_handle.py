from __future__ import annotations

import logging
from typing import Any
import uuid

from backend.channels import EvolutionWhatsAppChannel
from backend.dao.agent import AgentDAO
from backend.dao.agent_msg_hist import AgentMsgHistDAO
from backend.dao.assigned_task import AssignedTaskDAO
from backend.dao.session import AgentSessionDAO
from backend.dao.user_acc import UserAccDAO
from backend.db.session import async_session_factory
from backend.dto.session import AgentSessionCreate
from backend.entities.assigned_task import AssignedTaskStep
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.queues.message_queue import CmnMsgQueueTask, MessageQueue, TaskState
from backend.queues.task_queue import (
    TaskQueueHandlerResult,
    TaskQueueStep,
    TaskQueueStepStatus,
)

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
        if task.agent_type == "planner":
            approved_plan_html = (task.approved_plan_html or "").strip()
            if approved_plan_html:
                task.message += f"\n\n<html_plan>\n{approved_plan_html}\n</html_plan>"
    else:
        task.message = t("queues.task_queue_handle.continue_sub_agent_message")

    task.change_status(TaskQueueStepStatus.SEND)
    return None


async def handle_assigned_task_send_step(
    task: TaskQueueStep,
) -> TaskQueueHandlerResult | None:
    _log_started(task)

    msg_task: CmnMsgQueueTask = await MessageQueue.instance().create(
        agent_id=str(task.assign_agent_id),
        session_id=str(task.step_session_id),
        message=task.message,
    )

    resp_message: str = ""
    interrupt_message: str = ""
    while msg_task.task_state != TaskState.COMPLETED:
        async for chunk in msg_task.stream_gen():
            if chunk.chunk_type == "content":
                resp_message += chunk.content or ""
            elif chunk.chunk_type == "interrupt":
                resp_message = ""
                interrupt_message = _interrupt_message_from_chunk(chunk)
                logger.info(t("queues.task_queue_handle.interrupted"), task.step_id)
                msg_id = await _send_interrupt_to_user(task, chunk)
                if msg_id:
                    msg_task.ack_stream_callback(msg_id)

    logger.info(t("queues.task_queue_handle.message_queue_completed"))

    if resp_message and await _is_step_pending(task):
        task.message = resp_message
        logger.info(t("queues.task_queue_handle.response_message_received"))
        task.change_status(TaskQueueStepStatus.RESPONSE)
        return None
    logger.info(t("queues.task_queue_handle.completing_without_response"))
    return _complete_scaffold_task(task)


async def handle_assigned_task_response_step(
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


async def _is_step_pending(task: TaskQueueStep) -> bool:
    async with async_session_factory() as session:
        step = await session.get(AssignedTaskStep, task.step_db_id)
    return bool(step and step.status == "pending")


def _interrupt_message_from_chunk(chunk: Any) -> str:
    chunk_data = getattr(chunk, "data", None)
    data = chunk_data if isinstance(chunk_data, dict) else {}
    message = data.get("message") or getattr(chunk, "content", None) or ""
    return str(message)


async def _send_interrupt_to_user(task: TaskQueueStep, chunk: StreamChunk) -> str | None:
    interrupt_message = _interrupt_message_from_chunk(chunk)
    if not interrupt_message or task.responsible_agent_db_id is None:
        return None
    if task.user_db_id is None:
        return None

    async with async_session_factory() as session:
        responsible_agent = await AgentDAO(session).get_by_id(
            task.responsible_agent_db_id
        )
        user = await UserAccDAO(session).get_by_id(task.user_db_id)

    whatsapp_instance = getattr(responsible_agent, "whatsapp_instance", None)
    whatsapp_key = getattr(responsible_agent, "whatsapp_key", None)
    phoneno = getattr(user, "phoneno", None)

    if (
        responsible_agent is None
        or user is None
        or not whatsapp_instance
        or not whatsapp_key
        or not phoneno
    ):
        logger.info(
            t("queues.task_queue_handle.interrupt_whatsapp_missing_fields"),
            task.step_id,
            task.responsible_agent_id,
        )
        return None

    channel = EvolutionWhatsAppChannel(
        whatsapp_instance=whatsapp_instance,
        whatsapp_key=whatsapp_key,
    )
    try:
        document = _whatsapp_document_from_interrupt_data(chunk.data or {})
        if document:
            resp = await channel.send_document(
                phoneno,
                document["media"],
                mimetype=document.get("mimetype"),
                file_name=document.get("file_name"),
                caption=document.get("caption") or interrupt_message,
            )
        else:
            resp = await channel.send_text(phoneno, interrupt_message)
    finally:
        await channel.close()
    msg_id = _extract_message_id(resp)
    logger.info(
        t("queues.task_queue_handle.interrupt_whatsapp_sent"),
        task.step_id,
        phoneno,
        msg_id,
    )
    return msg_id


def _whatsapp_document_from_interrupt_data(
    interrupt_data: dict[str, Any],
) -> dict[str, str] | None:
    document = interrupt_data.get("whatsapp_document")
    if not isinstance(document, dict):
        return None
    media = document.get("media")
    if not isinstance(media, str) or not media:
        return None
    return {
        "media": media,
        "mimetype": str(document.get("mimetype") or "text/html"),
        "file_name": str(
            document.get("file_name")
            or t("graph.brainstormer.submit_approval.file_name")
        ),
        "caption": str(document.get("caption") or ""),
    }


def _extract_message_id(evolution_response: dict[str, Any]) -> str | None:
    if not isinstance(evolution_response, dict):
        return None
    key = evolution_response.get("key")
    if isinstance(key, dict):
        message_id = key.get("id")
        return message_id if isinstance(message_id, str) else None
    return None
