from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.dao.assigned_task import AssignedTaskDAO
from backend.db.session import async_session_factory
from backend.i18n import t

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class TaskQueueHandlerResult:
    success: bool
    log: str | None = None


TaskQueueHandler = Callable[[TaskQueueStep], Awaitable[TaskQueueHandlerResult]]


class TaskQueue:
    def __init__(
        self,
        handler: TaskQueueHandler,
        *,
        max_concurrency: int = 4,
        poll_interval_seconds: float = 5,
        session_factory: async_sessionmaker = async_session_factory,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError(t("queues.task_queue.invalid_max_concurrency"))
        if poll_interval_seconds <= 0:
            raise ValueError(t("queues.task_queue.invalid_poll_interval"))

        self._handler = handler
        self._max_concurrency = max_concurrency
        self._poll_interval_seconds = poll_interval_seconds
        self._session_factory = session_factory
        self._queue: asyncio.Queue[TaskQueueStep] = asyncio.Queue()
        self._poller: asyncio.Task[None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._active_responsible_agent_ids: set[int] = set()
        self._queued_step_ids: set[int] = set()

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
                excluded_responsible_agent_ids=self._active_responsible_agent_ids,
            )
            claimed = 0
            for step, responsible_agent_id in rows:
                if step.id in self._queued_step_ids:
                    continue
                if responsible_agent_id in self._active_responsible_agent_ids:
                    continue
                if claimed >= available_slots:
                    break

                if not await dao.mark_step_processing(step_db_id=step.id, now=now):
                    continue

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
                )
                await self._queue.put(task)
                self._queued_step_ids.add(step.id)
                self._active_responsible_agent_ids.add(responsible_agent_id)
                claimed += 1

            if claimed:
                await session.commit()

    async def _worker(self) -> None:
        while True:
            task = await self._queue.get()
            self._queued_step_ids.discard(task.step_db_id)
            try:
                result = await self._run_handler(task)
                await self._record_result(task, result)
            finally:
                self._active_responsible_agent_ids.discard(task.responsible_agent_id)
                self._queue.task_done()

    async def _run_handler(self, task: TaskQueueStep) -> TaskQueueHandlerResult:
        try:
            return await self._handler(task)
        except Exception as exc:
            logger.exception(t("queues.task_queue.handler_failed"), task.step_id)
            return TaskQueueHandlerResult(success=False, log=str(exc))

    async def _record_result(
        self, task: TaskQueueStep, result: TaskQueueHandlerResult
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            dao = AssignedTaskDAO(session)
            if result.success:
                attempt_no = await dao.count_process_logs(step_db_id=task.step_db_id) + 1
                await dao.create_process_log(
                    step_db_id=task.step_db_id,
                    attempt_no=attempt_no,
                    status="success",
                    started_at=task.started_at,
                    finished_at=finished_at,
                    log=result.log,
                )
                await dao.clear_step_processing(step_db_id=task.step_db_id)
            else:
                failed_attempt_no = await dao.count_failed_process_logs(
                    step_db_id=task.step_db_id
                ) + 1
                await dao.create_process_log(
                    step_db_id=task.step_db_id,
                    attempt_no=failed_attempt_no,
                    status="failed",
                    started_at=task.started_at,
                    finished_at=finished_at,
                    log=result.log,
                )
                await dao.clear_step_processing(
                    step_db_id=task.step_db_id,
                    next_run_at=finished_at + _retry_delay(failed_attempt_no),
                )
            await session.commit()


def _retry_delay(failed_attempt_no: int) -> timedelta:
    if failed_attempt_no <= 1:
        return timedelta(seconds=30)
    if failed_attempt_no == 2:
        return timedelta(seconds=60)
    if failed_attempt_no == 3:
        return timedelta(minutes=5)
    if failed_attempt_no == 4:
        return timedelta(minutes=10)
    if failed_attempt_no == 5:
        return timedelta(minutes=30)
    return timedelta(minutes=60)
