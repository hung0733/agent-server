from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.dao.assigned_task import AssignedTaskDAO
from backend.db.session import async_session_factory
from backend.i18n import t

if TYPE_CHECKING:
    from backend.entities import Agent

logger = logging.getLogger(__name__)


class TaskQueueStepStatus(StrEnum):
    INIT = "init"
    SEND = "send"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    COMPLETED = "completed"


@dataclass(frozen=True)
class TaskQueueHandlerResult:
    success: bool
    log: str | None = None


@dataclass
class TaskQueueStep:
    step_db_id: int
    step_id: str
    task_db_id: int
    task_id: str
    responsible_agent_id: int
    agent_type: str
    title: str
    goal: str
    seq_no: int
    started_at: datetime
    assign_agent_id: int | None = None
    agent_type_id: int | None = None
    responsible_agent: Agent | None = None
    assign_agent: Agent | None = None
    session_id: str = ""
    status: TaskQueueStepStatus = TaskQueueStepStatus.INIT
    process_log_db_id: int | None = None
    handler_result: TaskQueueHandlerResult | None = None

    def change_status(self, status: TaskQueueStepStatus) -> None:
        self.status = status


TaskQueueHandler = Callable[[TaskQueueStep], Awaitable[TaskQueueHandlerResult | None]]


_STATUS_PRIORITY = {
    TaskQueueStepStatus.COMPLETED: 0,
    TaskQueueStepStatus.RESUME: 1,
    TaskQueueStepStatus.INTERRUPT: 2,
    TaskQueueStepStatus.SEND: 3,
    TaskQueueStepStatus.INIT: 4,
}


class TaskQueue:
    def __init__(
        self,
        handlers: Mapping[TaskQueueStepStatus, TaskQueueHandler],
        *,
        max_concurrency: int = 4,
        poll_interval_seconds: float = 5,
        session_factory: async_sessionmaker = async_session_factory,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError(t("queues.task_queue.invalid_max_concurrency"))
        if poll_interval_seconds <= 0:
            raise ValueError(t("queues.task_queue.invalid_poll_interval"))

        self._handlers = dict(handlers)
        self._max_concurrency = max_concurrency
        self._poll_interval_seconds = poll_interval_seconds
        self._session_factory = session_factory
        self._queue: asyncio.PriorityQueue[tuple[int, int, TaskQueueStep]] = (
            asyncio.PriorityQueue()
        )
        self._poller: asyncio.Task[None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._active_responsible_agent_ids: set[int] = set()
        self._interrupted_responsible_agent_ids: set[int] = set()
        self._queued_step_ids: set[int] = set()
        self._counter = 0

    def start(self) -> None:
        if self._poller or self._workers:
            return
        self._poller = asyncio.create_task(self._poll_loop())
        self._workers = [
            asyncio.create_task(self._worker()) for _ in range(self._max_concurrency)
        ]

    async def stop(self) -> None:
        tasks = [task for task in [self._poller, *self._workers] if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._poller = None
        self._workers = []

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._enqueue_due_steps()
            except Exception:
                logger.exception(t("queues.task_queue.poll_failed"))
            await asyncio.sleep(self._poll_interval_seconds)

    async def _enqueue_due_steps(self) -> None:
        available_slots = self._max_concurrency - self._queue.qsize()
        if available_slots <= 0:
            return

        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            dao = AssignedTaskDAO(session)
            rows = await dao.list_due_pending_steps(
                now=now,
                limit=available_slots,
            )
            claimed = 0
            for step, responsible_agent_id in rows:
                if step.id in self._queued_step_ids:
                    continue
                if claimed >= available_slots:
                    break

                task = TaskQueueStep(
                    step_db_id=step.id,
                    step_id=step.step_id,
                    task_db_id=step.task_id,
                    task_id=step.task.task_id,
                    responsible_agent_id=responsible_agent_id,
                    agent_type=step.agent_type,
                    title=step.title,
                    goal=step.goal,
                    seq_no=step.seq_no,
                    started_at=now,
                    assign_agent_id=step.assign_agent_id,
                    agent_type_id=step.agent_type_id,
                    responsible_agent=step.task.responsible_agent,
                    assign_agent=step.assign_agent,
                    session_id=_step_session_id(step),
                )
                await self._enqueue_task(task)
                self._queued_step_ids.add(step.id)
                claimed += 1

            if claimed:
                await session.commit()

    async def _worker(self) -> None:
        while True:
            _, _, task = await self._queue.get()
            try:
                completed = await self._handle_task(task)
                if not completed:
                    await self._enqueue_task(task)
                    await asyncio.sleep(0)
                else:
                    self._queued_step_ids.discard(task.step_db_id)
            finally:
                self._queue.task_done()

    async def _enqueue_task(self, task: TaskQueueStep) -> None:
        self._sync_interrupt_state(task)
        await self._queue.put((_STATUS_PRIORITY[task.status], self._counter, task))
        self._counter += 1

    async def _handle_task(self, task: TaskQueueStep) -> bool:
        if await self._should_wait(task):
            return False

        if task.status == TaskQueueStepStatus.COMPLETED:
            return await self._complete_task_if_ready(task)

        handler = self._handlers.get(task.status)
        if handler is None:
            return False

        self._active_responsible_agent_ids.add(task.responsible_agent_id)
        try:
            await self._ensure_process_log(task)
            result = await self._run_handler(task, handler)
            if result is not None:
                task.handler_result = result
            self._sync_interrupt_state(task)
            if task.status == TaskQueueStepStatus.COMPLETED:
                return await self._complete_task_if_ready(task)
            return False
        finally:
            self._active_responsible_agent_ids.discard(task.responsible_agent_id)

    async def _should_wait(self, task: TaskQueueStep) -> bool:
        if task.status == TaskQueueStepStatus.COMPLETED:
            return False
        if task.responsible_agent_id in self._active_responsible_agent_ids:
            return True
        if task.status in (
            TaskQueueStepStatus.INIT,
            TaskQueueStepStatus.SEND,
        ):
            return task.responsible_agent_id in self._interrupted_responsible_agent_ids
        return False

    async def _run_handler(
        self, task: TaskQueueStep, handler: TaskQueueHandler
    ) -> TaskQueueHandlerResult | None:
        try:
            return await handler(task)
        except Exception as exc:
            logger.exception(t("queues.task_queue.handler_failed"), task.step_id)
            return TaskQueueHandlerResult(success=False, log=str(exc))

    async def _ensure_process_log(self, task: TaskQueueStep) -> None:
        if task.process_log_db_id is not None:
            return

        async with self._session_factory() as session:
            dao = AssignedTaskDAO(session)
            attempt_no = await dao.count_process_logs(step_db_id=task.step_db_id) + 1
            log = await dao.create_process_log(
                step_db_id=task.step_db_id,
                attempt_no=attempt_no,
                status="processing",
                started_at=task.started_at,
                finished_at=None,
                log=None,
            )
            task.process_log_db_id = log.id
            await session.commit()

    async def _complete_task_if_ready(self, task: TaskQueueStep) -> bool:
        if task.handler_result is None:
            return False

        finished_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            dao = AssignedTaskDAO(session)
            await dao.finish_process_log(
                process_log_db_id=task.process_log_db_id,
                status="success" if task.handler_result.success else "failed",
                finished_at=finished_at,
                log=task.handler_result.log,
            )
            await session.commit()
        self._interrupted_responsible_agent_ids.discard(task.responsible_agent_id)
        return True

    def _sync_interrupt_state(self, task: TaskQueueStep) -> None:
        if task.status == TaskQueueStepStatus.INTERRUPT:
            self._interrupted_responsible_agent_ids.add(task.responsible_agent_id)
        elif task.status in (
            TaskQueueStepStatus.RESUME,
            TaskQueueStepStatus.COMPLETED,
        ):
            self._interrupted_responsible_agent_ids.discard(task.responsible_agent_id)


def _step_session_id(step: object) -> str:
    step_session = getattr(step, "session", None)
    if step_session is not None:
        return str(step_session.session_id)

    task = getattr(step, "task", None)
    task_session = getattr(task, "session", None)
    if task_session is not None:
        return str(task_session.session_id)

    return ""
