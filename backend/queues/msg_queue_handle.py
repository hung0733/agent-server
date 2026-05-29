from __future__ import annotations

from backend.agent.agent import Agent
from backend.llm.types import StreamChunk
from backend.queues.message_queue import MsgQueueTask
from backend.sandbox.manager import get_agent_sandbox


async def handle_agent_message(task: MsgQueueTask) -> None:
    agent = await Agent.get_agent(task.agent_id, task.session_id)
    sandbox = await get_agent_sandbox(agent.agent_id, agent.user_id)
    done_sent = False

    async for chunk in agent.send(
        task.message,
        think_mode=False,
        metadata={"source": "whatsapp", "files": task.files},
        sandbox=sandbox,
    ):
        await task.callback(chunk)
        if chunk.chunk_type == "done":
            done_sent = True

    if not done_sent:
        await task.callback(StreamChunk(chunk_type="done"))
