from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import TypedDict

from backend.i18n import t
from backend.llm.types import StreamChunk


logger = logging.getLogger(__name__)


class FilePayload(TypedDict):
    mimetype: str | None
    filename: str | None
    bytes: bytes


class MessagePayload(TypedDict):
    agent_id: str
    session_id: str
    message: str
    files: list[FilePayload] | None


LLMStreamResult = AsyncIterator[StreamChunk] | Awaitable[AsyncIterator[StreamChunk] | None] | None
LLMStreamHandler = Callable[[MessagePayload], LLMStreamResult]


class _QueueRequest(TypedDict):
    payload: MessagePayload
    response_queue: asyncio.Queue[StreamChunk]


class MessageQueue:
    def __init__(self, llm_stream_handler: LLMStreamHandler, max_concurrency: int = 2) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._llm_stream_handler = llm_stream_handler
        self._queue: asyncio.Queue[_QueueRequest] = asyncio.Queue()
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

    async def create_msg_queue(self, payload: MessagePayload) -> AsyncGenerator[StreamChunk, None]:
        if not payload["agent_id"] or not payload["session_id"]:
            raise ValueError("agent_id and session_id are required")

        self.start()
        response_queue: asyncio.Queue[StreamChunk] = asyncio.Queue()
        await self._queue.put({"payload": payload, "response_queue": response_queue})

        while True:
            chunk = await response_queue.get()
            yield chunk
            if chunk.chunk_type == "done":
                break

    async def _worker(self) -> None:
        while True:
            request = await self._queue.get()
            try:
                await self._handle_request(request)
            finally:
                self._queue.task_done()

    async def _handle_request(self, request: _QueueRequest) -> None:
        response_queue = request["response_queue"]
        try:
            result = self._llm_stream_handler(request["payload"])
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                async for chunk in result:
                    await response_queue.put(chunk)
        except Exception as exc:
            logger.exception(t("queues.message_queue.handler_failed"))
            await response_queue.put(
                StreamChunk(
                    chunk_type="done",
                    data={"error": str(exc)},
                )
            )
            return

        await response_queue.put(StreamChunk(chunk_type="done"))


async def create_msg_queue(
    message_queue: MessageQueue,
    payload: MessagePayload,
) -> AsyncGenerator[StreamChunk, None]:
    async for chunk in message_queue.create_msg_queue(payload):
        yield chunk
