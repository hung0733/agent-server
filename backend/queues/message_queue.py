from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypedDict

from backend.i18n import t
from backend.llm.types import StreamChunk


logger = logging.getLogger(__name__)


class FilePayload(TypedDict):
    mimetype: str | None
    filename: str | None
    bytes: bytes


@dataclass
class MsgQueueTask:
    message: str
    agent_id: str
    session_id: str
    files: list[FilePayload] | None = None

    async def callback(self, chunk: StreamChunk) -> None:
        return None


MsgQueueHandler = Callable[[MsgQueueTask], Awaitable[None]]


class MessageQueue:
    def __init__(self, handler: MsgQueueHandler, max_concurrency: int = 2) -> None:
        if max_concurrency < 1 or max_concurrency > 2:
            raise ValueError("max_concurrency must be between 1 and 2")
        self._handler = handler
        self._queue: asyncio.Queue[MsgQueueTask] = asyncio.Queue()
        self._max_concurrency = max_concurrency
        self._workers: list[asyncio.Task[None]] = []

    def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker())
            for _ in range(self._max_concurrency)
        ]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._workers = []

    async def enqueue(self, task: MsgQueueTask) -> None:
        if not task.agent_id or not task.session_id:
            raise ValueError("agent_id and session_id are required")

        self.start()
        await self._queue.put(task)

    async def _worker(self) -> None:
        while True:
            task = await self._queue.get()
            try:
                await self._handle_task(task)
            finally:
                self._queue.task_done()

    async def _handle_task(self, task: MsgQueueTask) -> None:
        try:
            await self._handler(task)
        except Exception as exc:
            logger.exception(t("queues.message_queue.handler_failed"))
            await task.callback(
                StreamChunk(
                    chunk_type="done",
                    data={"error": str(exc)},
                )
            )
