from __future__ import annotations

import logging
from typing import AsyncGenerator

from backend.agent.agent import Agent
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.queues.message_queue import MessageQueue, MsgQueueTask, TaskState
from backend.sandbox.manager import get_agent_sandbox

logger = logging.getLogger(__name__)


async def handle_agent_message(task: MsgQueueTask) -> bool:
    logger.info(
        t("queues.msg_queue_handle.started"),
        task.agent_id,
        task.session_id,
        task.task_state,
        len(task.message),
        bool(task.files),
    )

    agent = await Agent.get_agent(task.agent_id, task.session_id)
    sandbox = await get_agent_sandbox(agent.agent_id, agent.user_id)
    done_sent = False

    gen: AsyncGenerator = (
        agent.send(
            task.message,
            think_mode=False,
            metadata={"source": "whatsapp", "files": task.files},
            sandbox=sandbox,
        )
        if task.task_state != TaskState.RESUME
        else agent.resume(
            task.message,
            think_mode=False,
            metadata={"source": "whatsapp", "files": task.files},
            sandbox=sandbox,
        )
    )

    async for chunk in gen:
        msg_id = await task.callback(chunk)
        if chunk.chunk_type == "done":
            done_sent = True
        elif chunk.chunk_type == "interrupt" and msg_id:
            task.wait_msg_id = msg_id

    if not done_sent:
        logger.debug(
            t("queues.msg_queue_handle.done_sent"), task.agent_id, task.session_id
        )
        await task.callback(StreamChunk(chunk_type="done"))

    if task.wait_msg_id:
        logger.info(
            t("queues.msg_queue_handle.interrupted"),
            task.agent_id,
            task.session_id,
            task.wait_msg_id,
        )
        return False
    logger.info(
        t("queues.msg_queue_handle.completed"), task.agent_id, task.session_id
    )
    return True
