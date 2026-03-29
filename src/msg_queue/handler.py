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

from decimal import Decimal
from datetime import datetime
import logging
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import UUID, uuid4

from agent.agent import Agent
from agent.bulter import Bulter
from db.dao.agent_message_dao import AgentMessageDAO
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dao.token_usage_dao import TokenUsageDAO
from db.dto.collaboration_dto import AgentMessageCreate
from db.dto.token_usage_dto import TokenUsageCreate
from db.types import MessageType
from i18n import _
from models.llm import LLMSet
from msg_queue.manager import QueueManager, get_queue_manager
from msg_queue.models import (
    QueueTaskPriority,
    QueueTaskState,
    StreamChunk,
)
from msg_queue.task import QueueTask
from utils.tools import Tools

logger = logging.getLogger(__name__)


class MsgQueueHandler:

    @staticmethod
    async def create_msg_queue(
        agent_id: str,
        session_id: str,
        message: str,
        system_prompt: Optional[str] = None,
        think_mode: Optional[bool] = None,
        priority: QueueTaskPriority = QueueTaskPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Enqueue a task and return an async generator of StreamChunks."""
        qm = get_queue_manager()
        logger.debug(
            _("Creating queue task for agent=%s session=%s"), agent_id, session_id
        )
        logger.debug(
            _("DEBUG: QueueManager instance (id=%s, running=%s, handlers=%s)"),
            id(qm),
            qm._running,
            list(qm._state_handlers.keys()),
        )
        task_id, gen = await qm.enqueue(
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            system_prompt=system_prompt,
            priority=priority,
            metadata=metadata,
            think_mode=think_mode,
        )
        logger.debug(_("Task %s enqueued"), task_id)
        async for chunk in gen:
            yield chunk

    # ------------------------------------------------------------------
    # Pipeline stages (register these with QueueManager at startup)
    # ------------------------------------------------------------------

    @staticmethod
    async def collect_db_data(task: QueueTask) -> None:
        """Load the Agent object from DB."""
        logger.debug(_("Task %s: collect_db_data (agent=%s)"), task.id, task.agent_id)
        try:
            task.agent = await Bulter.get_agent(task.agent_id, task.session_id)
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
        logger.debug(_("Task %s: pack_memory"), task.id)
        try:
            if task.system_prompt is not None:
                task.packed_prompt = task.system_prompt
            else:
                task.packed_prompt = await task.agent.get_memory_prompt()  # type: ignore
                task.packed_prompt += "現在時間: " + datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n"  # type: ignore

            task.update_state(QueueTaskState.PACKED_MEMORY)
        except Exception as exc:
            logger.error(_("Task %s: pack_memory failed: %s"), task.id, exc)
            task.update_state(QueueTaskState.ERROR)
            task.error = str(exc)
            raise

    @staticmethod
    async def pack_message(task: QueueTask) -> None:
        """Finalise the user message string."""
        logger.debug(_("Task %s: pack_message"), task.id)
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
        logger.debug(_("Task %s: select_llm_model"), task.id)
        try:
            if task.agent is None:
                raise ValueError(_("Agent not initialised — run collect_db_data first"))

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
    async def _save_messages_to_db(
        task_id: str,
        session_db_id: str,
        sender_db_id: Optional[str],
        receiver_db_id: str,
        llm_response_content: list,
    ) -> None:
        """Background task to save messages to database.

        This runs in a separate async task to avoid blocking the streaming.
        """
        try:
            # Generate step_id for this conversation turn
            step_id = f"step-{uuid4()}"
            logger.debug(_("Task %s: generated step_id=%s"), task_id, step_id)

            # Map streaming chunk types to MessageType enum
            # "user" -> request (user asking)
            # "content", "think" -> response (LLM answering)
            # "tool" -> tool_call
            # "tool_result" -> tool_result
            type_mapping = {
                "user": MessageType.request,
                "content": MessageType.response,
                "think": MessageType.response,
                "tool": MessageType.tool_call,
                "tool_result": MessageType.tool_result,
            }

            # Convert to UUID, handle str/UUID/None
            # collaboration_id is required (cannot be None)
            if isinstance(session_db_id, UUID):
                collab_id = session_db_id
            elif isinstance(session_db_id, str) and session_db_id:
                collab_id = UUID(session_db_id)
            else:
                raise ValueError(
                    _("session_db_id is required and cannot be None or empty")
                )

            # sender_agent_id is optional (can be None)
            if isinstance(sender_db_id, UUID):
                sender_id = sender_db_id
            elif isinstance(sender_db_id, str) and sender_db_id:
                sender_id = UUID(sender_db_id)
            else:
                sender_id = None

            # receiver_agent_id is optional (can be None)
            if isinstance(receiver_db_id, UUID):
                receiver_id = receiver_db_id
            elif isinstance(receiver_db_id, str) and receiver_db_id:
                receiver_id = UUID(receiver_db_id)
            else:
                receiver_id = None

            for m in llm_response_content:
                msg_type_str = m.get("msg_type", "content")
                # Convert string to MessageType enum, default to response if unknown
                message_type = type_mapping.get(msg_type_str, MessageType.response)

                msg = await AgentMessageDAO.create(
                    AgentMessageCreate(
                        collaboration_id=collab_id,
                        step_id=step_id,
                        sender_agent_id=sender_id,
                        receiver_agent_id=receiver_id,
                        message_type=message_type,
                        content_json={
                            "content": m.get("content", ""),
                            "tool_args": m.get("tool_args", ""),
                        },
                    )
                )

                logger.debug(
                    _("Task %s: logged message id=%s, type=%s"),
                    task_id,
                    msg.id,
                    message_type.value,
                )

            logger.debug(_("Task %s: all messages saved to database"), task_id)

        except Exception as exc:
            logger.error(
                _("Task %s: failed to save messages to database: %s"), task_id, exc
            )

    @staticmethod
    async def _save_token_usage(
        session_id: str,
        agent_db_id: str,
        usage_payload: dict[str, Any],
    ) -> None:
        if not usage_payload.get("available"):
            return

        session = await CollaborationSessionDAO.get_by_session_id(session_id)
        if session is None:
            logger.warning(_("Token usage skipped: session %s not found"), session_id)
            return

        await TokenUsageDAO.create(
            TokenUsageCreate(
                user_id=session.user_id,
                agent_id=UUID(agent_db_id),
                task_id=UUID(usage_payload["task_id"]) if usage_payload.get("task_id") else None,
                llm_endpoint_id=UUID(usage_payload["llm_endpoint_id"]) if usage_payload.get("llm_endpoint_id") else None,
                session_id=session_id,
                model_name=usage_payload.get("model") or "unknown",
                input_tokens=int(usage_payload.get("input_tokens") or 0),
                output_tokens=int(usage_payload.get("output_tokens") or 0),
                total_tokens=int(usage_payload.get("total_tokens") or 0),
                estimated_cost_usd=Decimal("0"),
            )
        )

    @staticmethod
    async def send_llm_msg(task: QueueTask) -> None:
        """Stream the LLM response and push chunks to the task queue."""
        logger.debug(_("Task %s: send_llm_msg"), task.id)
        try:
            if task.agent is None:
                raise ValueError(_("Agent not initialised — run collect_db_data first"))
            if task.packed_message is None:
                raise ValueError(_("Message not packed — run pack_message first"))

            task.update_state(QueueTaskState.SENDING_TO_LLM)

            # Collect LLM response for logging
            llm_response_content = []
            llm_response_content.append(
                {
                    "msg_type": "user",
                    "content": task.packed_message,
                    "tool_args": "",
                }
            )

            gen = task.agent.send(
                models=task.model_set,
                sys_prompt=task.packed_prompt,
                message=task.packed_message,
                think_mode=task.think_mode,
                metadata=task.metadata,
            )
            task.update_state(QueueTaskState.RECEIVING_STREAM)
            task.update_state(QueueTaskState.STREAMING_TO_CLIENT)

            content: str = ""
            tool_args: str = ""
            chunk_type = ""
            usage_payload: Optional[Dict[str, Any]] = None

            async for chunk in gen:
                await task.stream_callback(chunk)
                if chunk.chunk_type == "usage" and chunk.data:
                    usage_payload = chunk.data.get("usage")
                if not chunk_type and chunk_type != chunk.chunk_type:
                    if len(content) > 0:
                        llm_response_content.append(
                            {
                                "msg_type": chunk_type,
                                "content": content,
                                "tool_args": tool_args,
                            }
                        )
                        # Log message content for debugging
                        logger.info(
                            _(
                                "Task %s: message chunk - type=%s, content_length=%d, has_tool_args=%s"
                            ),
                            task.id,
                            chunk_type,
                            len(content),
                            bool(tool_args),
                        )

                    content = ""
                    tool_args = ""
                    chunk_type = chunk.chunk_type
                content += "" if chunk.content is None else chunk.content
                if chunk_type == "tool":
                    tool_args += (
                        ""
                        if chunk.data is None
                        or not chunk.data.get("tool_call", {}).get("args")
                        else chunk.data["tool_call"]["args"]
                    )

            if len(content) > 0 and len(chunk_type) > 0:
                llm_response_content.append(
                    {
                        "msg_type": chunk_type,
                        "content": content,
                        "tool_args": tool_args,
                    }
                )
                # Log message content for debugging
                logger.info(_("Task %s: %s, %s"), task.id, content, tool_args)

            should_persist = task.metadata.get("source") != "review_msg"

            if should_persist:
                # Create background tasks to save messages (DB + long-term memory)
                Tools.start_async_task(
                    MsgQueueHandler._save_messages_to_db(
                        task_id=task.id,
                        session_db_id=task.agent.session_db_id,
                        sender_db_id=None,
                        receiver_db_id=task.agent.agent_db_id,
                        llm_response_content=llm_response_content,
                    )
                )

                Tools.start_async_task(task.agent.review_stm(task.model_set))

                if usage_payload is not None:
                    Tools.start_async_task(
                        MsgQueueHandler._save_token_usage(
                            session_id=task.session_id,
                            agent_db_id=task.agent.agent_db_id,
                            usage_payload=usage_payload,
                        )
                    )

                logger.debug(
                    _("Task %s: background save tasks created (DB + memory)"), task.id
                )
            else:
                logger.debug(
                    _("Task %s: skip persistence for internal review_msg analysis"),
                    task.id,
                )

            await task.stream_callback(StreamChunk(chunk_type="done"))
            task.update_state(QueueTaskState.COMPLETED)
            result = {"task_id": task.id, "status": "completed"}
            if usage_payload is not None:
                result["usage"] = usage_payload
            await task.complete_callback(result)

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
