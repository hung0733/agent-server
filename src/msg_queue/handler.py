"""MsgQueueHandler — LLM pipeline stages for QueueTask processing.

Each static method handles one state in the pipeline.
Register them with QueueManager.register_state_handler() at startup.

Pipeline order:
  INIT
  → collect_db_data      (load agent from DB)
  → pack_sys_prompt      (assemble system prompt)
  → pack_memory          (attach long-term memory)
  → pack_message         (finalise user message)
  → analyse_msg_diff     (classify difficulty)
  → select_llm_model     (pick model based on difficulty)
  → send_llm_msg         (stream LLM → callback → WhatsApp)
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from agent.bulter import Bulter
from i18n import _
from models.llm import LLMSet
from msg_queue.manager import QueueManager, get_queue_manager
from msg_queue.models import (
    QueueTaskPriority,
    QueueTaskState,
    QueueTaskStatus,
    StreamChunk,
)
from msg_queue.task import QueueTask

logger = logging.getLogger(__name__)


class MsgQueueHandler:

    @staticmethod
    async def create_msg_queue(
        agent_id: str,
        session_id: str,
        message: str,
        think_mode: Optional[bool] = None,
        priority: QueueTaskPriority = QueueTaskPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Enqueue a task and return an async generator of StreamChunks."""
        qm = get_queue_manager()
        logger.info(
            _("Creating queue task for agent=%s session=%s"), agent_id, session_id
        )
        task_id, gen = await qm.enqueue(
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            priority=priority,
            metadata=metadata,
            think_mode=think_mode,
        )
        logger.info(_("Task %s enqueued"), task_id)
        async for chunk in gen:
            yield chunk

    # ------------------------------------------------------------------
    # Pipeline stages (register these with QueueManager at startup)
    # ------------------------------------------------------------------

    @staticmethod
    async def collect_db_data(task: QueueTask) -> None:
        """Load the Agent object from DB."""
        logger.info(_("Task %s: collect_db_data (agent=%s)"), task.id, task.agent_id)
        try:
            task.agent = Bulter.get_agent(task.agent_id, task.session_id)
        except NotImplementedError:
            raise
        except Exception as exc:
            logger.error(_("Task %s: collect_db_data failed: %s"), task.id, exc)
            task.update_state(QueueTaskState.ERROR)
            task.error = str(exc)
            raise
        task.update_state(QueueTaskState.COLLECTED_DB_DATA)

    @staticmethod
    async def pack_memory(task: QueueTask) -> None:
        """Attach long-term memory context to the message."""
        logger.info(_("Task %s: pack_memory"), task.id)
        try:
            task.packed_prompt = await task.agent.get_memory_prompt() # type: ignore
            task.packed_prompt += "現在時間: " + datetime.now().isoformat("YYYY-MM-DD HH:MM") + "\n\n"
            
            task.update_state(QueueTaskState.PACKED_MEMORY)
        except Exception as exc:
            logger.error(_("Task %s: pack_memory failed: %s"), task.id, exc)
            task.update_state(QueueTaskState.ERROR)
            task.error = str(exc)
            raise

    @staticmethod
    async def pack_message(task: QueueTask) -> None:
        """Finalise the user message string."""
        logger.info(_("Task %s: pack_message"), task.id)
        try:
            if task.packed_message is None:
                task.packed_message = ""
            task.packed_message += task.message or ""
            task.update_state(QueueTaskState.MESSAGES_PACKED)
        except Exception as exc:
            logger.error(_("Task %s: pack_message failed: %s"), task.id, exc)
            task.update_state(QueueTaskState.ERROR)
            task.error = str(exc)
            raise

    @staticmethod
    async def select_llm_model(task: QueueTask) -> None:
        """Pick LLM model(s) based on msg_diff_level."""
        logger.info(_("Task %s: select_llm_model"), task.id)
        try:
            if task.agent is None:
                raise ValueError("Agent not initialised — run collect_db_data first")

            from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
            from uuid import UUID
            endpoints = await LLMLevelEndpointDAO.get_by_agent_instance_id(
                UUID(task.agent.agent_db_id)
            )
            task.model_set = LLMSet.from_model(endpoints)
            task.update_state(QueueTaskState.SELECTED_LLM_MODEL)
        except Exception as exc:
            logger.error(_("Task %s: select_llm_model failed: %s"), task.id, exc)
            task.update_state(QueueTaskState.ERROR)
            task.error = str(exc)
            raise

    @staticmethod
    async def send_llm_msg(task: QueueTask) -> None:
        """Stream the LLM response and push chunks to the task queue."""
        logger.info(_("Task %s: send_llm_msg"), task.id)
        try:
            if task.agent is None:
                raise ValueError("Agent not initialised — run collect_db_data first")
            if task.packed_message is None:
                raise ValueError("Message not packed — run pack_message first")

            task.update_state(QueueTaskState.SENDING_TO_LLM)

            gen = task.agent.send(models=task.model_set, sys_prompt=task.packed_prompt, message=task.packed_message, think_mode=task.think_mode, metadata=task.metadata)
            task.update_state(QueueTaskState.RECEIVING_STREAM)
            task.update_state(QueueTaskState.STREAMING_TO_CLIENT)
            async for chunk in gen:
                await task.stream_callback(chunk)

            await task.stream_callback(StreamChunk(chunk_type="done"))
            task.update_state(QueueTaskState.COMPLETED)
            await task.complete_callback({"task_id": task.id, "status": "completed"})

        except Exception as exc:
            logger.error(_("Task %s: send_llm_msg failed: %s"), task.id, exc)
            task.update_state(QueueTaskState.ERROR)
            task.error = str(exc)
            raise


def register_all_handlers(qm: Optional[QueueManager] = None) -> QueueManager:
    """Register the full pipeline on *qm* (default: global singleton).

    Call this at application startup after QueueManager.start().
    """
    if qm is None:
        qm = get_queue_manager()

    qm.register_state_handler(QueueTaskState.INIT, MsgQueueHandler.collect_db_data)
    qm.register_state_handler(
        QueueTaskState.COLLECTED_DB_DATA, MsgQueueHandler.pack_memory
    )
    qm.register_state_handler(
        QueueTaskState.PACKED_MEMORY, MsgQueueHandler.pack_message
    )
    qm.register_state_handler(
        QueueTaskState.MESSAGES_PACKED, MsgQueueHandler.select_llm_model
    )
    qm.register_state_handler(
        QueueTaskState.SELECTED_LLM_MODEL, MsgQueueHandler.send_llm_msg
    )
    return qm
