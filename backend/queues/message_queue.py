from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

from backend.i18n import t
from backend.llm.types import StreamChunk

logger = logging.getLogger(__name__)


class FilePayload(TypedDict):
    mimetype: str | None
    filename: str | None
    bytes: bytes


class TaskState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    INTERRUPT = "interrupt"
    RESUME = "resume"


@dataclass
class MsgQueueTask:
    message: str
    agent_id: str
    session_id: str
    files: list[FilePayload] | None = None
    wait_msg_id: str | None = None
    task_state: str = TaskState.PENDING

    async def callback(self, chunk: StreamChunk) -> str | None:
        return None

    def change_task_state(self, state: TaskState) -> None:
        self.task_state = state


MsgQueueHandler = Callable[[MsgQueueTask], Awaitable[bool]]


class MessageQueue:
    def __init__(self, handler: MsgQueueHandler, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError(t("queues.message_queue.invalid_max_concurrency"))
        self._handler = handler
        self._queue: asyncio.PriorityQueue[tuple[int, int, MsgQueueTask]] = (
            asyncio.PriorityQueue()
        )
        self._max_concurrency = max_concurrency
        self._workers: list[asyncio.Task[None]] = []
        self._counter = 0
        self._agent_state: dict[str, str] = {}
        self._interrupt_tasks: dict[tuple[str, str], MsgQueueTask] = {}

    def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker()) for _ in range(self._max_concurrency)
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

    async def resume_interrupt(
        self, agent_id: str, msg_id: str, resume_task: MsgQueueTask | None = None
    ) -> bool:
        task = self._interrupt_tasks.pop((agent_id, msg_id), None)
        if not task:
            return False

        task.wait_msg_id = None
        if resume_task is not None:
            task.message = resume_task.message
            task.files = resume_task.files
            task.callback = resume_task.callback
        task.change_task_state(TaskState.RESUME)
        if self._agent_state.get(agent_id) == TaskState.INTERRUPT:
            self._agent_state.pop(agent_id, None)

        self.start()
        await self._enqueue_task(task)
        return True

    async def enqueue(self, task: MsgQueueTask) -> None:
        if not task.agent_id or not task.session_id:
            raise ValueError("agent_id and session_id are required")

        self.start()
        await self._enqueue_task(task)

    async def _enqueue_task(self, task: MsgQueueTask) -> None:
        priority = 0 if task.task_state == TaskState.RESUME else 1
        await self._queue.put((priority, self._counter, task))
        self._counter += 1

    async def _worker(self) -> None:
        while True:
            _, _, task = await self._queue.get()

            passed: bool = await self._handle_task(task)
            if passed or task.task_state == TaskState.INTERRUPT:
                self._queue.task_done()

    async def _handle_task(self, task: MsgQueueTask) -> bool:
        agent_state = self._agent_state.get(task.agent_id)
        if agent_state in ("processing", "interrupt"):
            await self._enqueue_task(task)
            self._queue.task_done()
            await asyncio.sleep(0)
            return False

        self._agent_state[task.agent_id] = "processing"
        try:
            return await self._run_handler(task)
        finally:
            if task.wait_msg_id:
                self._agent_state[task.agent_id] = TaskState.INTERRUPT
                task.change_task_state(TaskState.INTERRUPT)
                self._interrupt_tasks[(task.agent_id, task.wait_msg_id)] = task
            else:
                self._agent_state.pop(task.agent_id, None)

    async def _run_handler(self, task: MsgQueueTask) -> bool:
        try:
            return await self._handler(task)
        except Exception as exc:
            logger.exception(t("queues.message_queue.handler_failed"))
            await task.callback(
                StreamChunk(
                    chunk_type="done",
                    data={"error": str(exc)},
                )
            )
            return True
