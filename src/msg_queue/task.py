"""QueueTask — unit of work processed by QueueManager."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from pydantic import BaseModel, Field

from msg_queue.models import (
    MsgDiffLevel,
    QueueTaskPriority,
    QueueTaskState,
    QueueTaskStatus,
    StreamChunk,
)

logger = logging.getLogger(__name__)


class QueueTask(BaseModel):
    """A single agent task with priority, state machine and streaming output."""

    # Identity
    id: str = Field(default_factory=lambda: f"task_{uuid.uuid4()}")
    agent_id: str
    session_id: str

    # Input
    message: str
    think_mode: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Scheduling
    priority: QueueTaskPriority = QueueTaskPriority.NORMAL
    created_at: float = Field(default_factory=time.time)

    # Runtime
    status: QueueTaskStatus = QueueTaskStatus.PENDING
    state: QueueTaskState = QueueTaskState.INIT
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None

    # Pipeline intermediates (populated by handler stages)
    packed_message: Optional[str] = None
    packed_prompt: Optional[str] = None
    msg_diff_level: Optional[MsgDiffLevel] = None
    selected_models: Optional[list] = None  # list[BaseChatModel] once LLM layer exists
    agent: Optional[Any] = None  # Agent instance once graph layer exists

    # Internal stream channel
    _queue: asyncio.Queue = None  # type: ignore[assignment]

    class Config:
        arbitrary_types_allowed = True

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "_queue", asyncio.Queue())

    # ------------------------------------------------------------------
    # Callbacks (called by handler to push data into the stream)
    # ------------------------------------------------------------------

    async def stream_callback(self, chunk: StreamChunk) -> None:
        await self._queue.put(chunk)

    async def complete_callback(self, result: dict) -> None:
        await self._queue.put(None)

    async def error_callback(self, error: str) -> None:
        logger.error("Task %s error: %s", self.id, error)
        await self._queue.put(None)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def update_state(self, new_state: QueueTaskState) -> None:
        self.state = new_state

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def stream_gen(self) -> AsyncGenerator[StreamChunk, None]:
        """Async generator that yields StreamChunks until the task ends."""

        async def _gen() -> AsyncGenerator[StreamChunk, None]:
            try:
                while True:
                    chunk = await self._queue.get()
                    if chunk is None:
                        logger.debug("Task %s: stream ended", self.id)
                        return
                    yield chunk
            except GeneratorExit:
                logger.debug("Task %s: generator force-closed", self.id)
            except Exception as exc:
                logger.error("Task %s: stream_gen error: %s", self.id, exc)
                yield StreamChunk(chunk_type="done")

        return _gen()
