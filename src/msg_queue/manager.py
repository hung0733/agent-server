"""Central QueueManager — priority scheduling, concurrency, state dispatch."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Dict, Optional

from i18n import _
from msg_queue.models import (
    QueueStats,
    QueueTaskPriority,
    QueueTaskState,
    QueueTaskStatus,
    StreamChunk,
)
from msg_queue.task import QueueTask

logger = logging.getLogger(__name__)

StateHandler = Callable[[QueueTask], Awaitable[None]]


class QueueManager:
    """Central task queue with priority scheduling and state-based dispatch.

    Args:
        max_concurrent_tasks: Max tasks processed simultaneously.
        max_queue_size:        Hard limit on queued (pending) tasks.
        max_workers:           Thread-pool size for sync-in-async helpers.
    """

    def __init__(
        self,
        max_concurrent_tasks: int = 5,
        max_queue_size: int = 100,
        max_workers: int = 10,
    ) -> None:
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_queue_size = max_queue_size

        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # One deque per priority level (highest processed first)
        self._queues: Dict[QueueTaskPriority, deque] = {
            QueueTaskPriority.CRITICAL: deque(),
            QueueTaskPriority.HIGH: deque(),
            QueueTaskPriority.NORMAL: deque(),
            QueueTaskPriority.LOW: deque(),
        }

        self._processing: Dict[str, QueueTask] = {}
        self._all_tasks: Dict[str, QueueTask] = {}

        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._lock = asyncio.Lock()

        self._running = False
        self._processor_task: Optional[asyncio.Task] = None

        # state → handler mapping
        self._state_handlers: Dict[QueueTaskState, StateHandler] = {}
        # optional per-state concurrency cap
        self._state_semaphores: Dict[QueueTaskState, asyncio.Semaphore] = {}

        logger.info(
            _("QueueManager initialised (max_concurrent=%d, max_queue=%d, max_workers=%d)"),
            max_concurrent_tasks,
            max_queue_size,
            max_workers,
        )

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_state_handler(
        self,
        state: QueueTaskState,
        handler: StateHandler,
        max_connections: Optional[int] = None,
    ) -> None:
        self._state_handlers[state] = handler
        if max_connections is not None:
            self._state_semaphores[state] = asyncio.Semaphore(max_connections)
            logger.info(
                _("Registered handler for state=%s (max_connections=%d)"),
                state.value,
                max_connections,
            )
        else:
            logger.info(_("Registered handler for state=%s"), state.value)

    def unregister_state_handler(self, state: QueueTaskState) -> None:
        self._state_handlers.pop(state, None)
        self._state_semaphores.pop(state, None)
        logger.info(_("Unregistered handler for state=%s"), state.value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        agent_id: str,
        session_id: str,
        message: str,
        think_mode: Optional[bool] = None,
        priority: QueueTaskPriority = QueueTaskPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Any]:  # (task_id, AsyncGenerator[StreamChunk, None])
        """Add a task to the queue and return (task_id, stream_generator).

        Raises:
            ValueError: when the queue is full.
        """
        async with self._lock:
            current_size = sum(len(q) for q in self._queues.values())
            if current_size >= self.max_queue_size:
                raise ValueError(
                    _("Queue is full (max_size=%d)") % self.max_queue_size
                )

            task = QueueTask(
                agent_id=agent_id,
                session_id=session_id,
                message=message,
                priority=priority,
                think_mode=think_mode,
                metadata=metadata or {},
            )

            self._queues[priority].append(task)
            self._all_tasks[task.id] = task

        logger.info(
            _("Task %s enqueued (priority=%s, agent=%s)"),
            task.id,
            priority.value,
            agent_id,
        )
        return task.id, await task.stream_gen()

    async def cancel_task(self, task_id: str) -> bool:
        async with self._lock:
            task = self._all_tasks.get(task_id)
            if not task:
                return False
            if task.status == QueueTaskStatus.PROCESSING:
                logger.warning(_("Task %s is processing — cannot cancel"), task_id)
                return False
            if task.status == QueueTaskStatus.PENDING:
                for q in self._queues.values():
                    try:
                        q.remove(task)
                        task.status = QueueTaskStatus.CANCELLED
                        task.completed_at = time.time()
                        logger.info(_("Task %s cancelled"), task_id)
                        return True
                    except ValueError:
                        continue
        return False

    async def get_task(self, task_id: str) -> Optional[QueueTask]:
        return self._all_tasks.get(task_id)

    async def get_stats(self) -> QueueStats:
        async with self._lock:
            pending = sum(len(q) for q in self._queues.values())
            processing = len(self._processing)
            completed = sum(
                1 for t in self._all_tasks.values()
                if t.status == QueueTaskStatus.COMPLETED
            )
            failed = sum(
                1 for t in self._all_tasks.values()
                if t.status == QueueTaskStatus.FAILED
            )
            cancelled = sum(
                1 for t in self._all_tasks.values()
                if t.status == QueueTaskStatus.CANCELLED
            )
            times = [
                t.completed_at - t.started_at
                for t in self._all_tasks.values()
                if t.status == QueueTaskStatus.COMPLETED
                and t.started_at and t.completed_at
            ]
            return QueueStats(
                total_tasks=len(self._all_tasks),
                pending_tasks=pending,
                processing_tasks=processing,
                completed_tasks=completed,
                failed_tasks=failed,
                cancelled_tasks=cancelled,
                avg_processing_time=sum(times) / len(times) if times else None,
            )

    async def wait_for_completion(self, timeout: Optional[float] = None) -> None:
        start = time.time()
        while True:
            async with self._lock:
                if not self._processing and all(
                    len(q) == 0 for q in self._queues.values()
                ):
                    return
            if timeout and (time.time() - start) > timeout:
                raise asyncio.TimeoutError(
                    f"Queue not empty after {timeout}s"
                )
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            logger.warning(_("QueueManager already running"))
            return
        self._running = True
        self._processor_task = asyncio.create_task(
            self._queue_processor(), name="queue-manager"
        )
        logger.info(_("QueueManager started"))

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
        self._executor.shutdown(wait=True)
        logger.info(_("QueueManager stopped"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_in_thread(self, func: Callable, *args: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    async def _get_next_task(self) -> Optional[QueueTask]:
        for priority in (
            QueueTaskPriority.CRITICAL,
            QueueTaskPriority.HIGH,
            QueueTaskPriority.NORMAL,
            QueueTaskPriority.LOW,
        ):
            if self._queues[priority]:
                return self._queues[priority].popleft()
        return None

    async def _dispatch_state(self, task: QueueTask) -> None:
        """Call the registered handler for the task's current state."""
        handler = self._state_handlers.get(task.state)
        if not handler:
            logger.warning(
                _("No handler for state=%s — skipping task %s"),
                task.state.value,
                task.id,
            )
            return
        logger.info(
            _("DEBUG: Dispatching task %s to handler for state=%s"),
            task.id,
            task.state.value,
        )
        sem = self._state_semaphores.get(task.state)
        if sem:
            async with sem:
                await handler(task)
        else:
            await handler(task)

    async def _process_task(self, task: QueueTask) -> None:
        task.status = QueueTaskStatus.PROCESSING
        task.started_at = time.time()
        self._processing[task.id] = task

        logger.info(_("Processing task %s (agent=%s)"), task.id, task.agent_id)
        try:
            # Drive the task through its state chain until no handler matches
            await self._dispatch_state(task)

            while task.status == QueueTaskStatus.PROCESSING:
                if task.state not in self._state_handlers:
                    break
                await self._dispatch_state(task)

            task.status = QueueTaskStatus.COMPLETED
            logger.info(_("Task %s completed"), task.id)

        except Exception as exc:
            logger.error(_("Task %s failed: %s"), task.id, exc)
            task.status = QueueTaskStatus.FAILED
            task.error = str(exc)
            try:
                await task.error_callback(str(exc))
            except Exception as cb_exc:
                logger.error(_("error_callback failed: %s"), cb_exc)
        finally:
            task.completed_at = time.time()
            self._processing.pop(task.id, None)

    async def _process_task_with_semaphore(self, task: QueueTask) -> None:
        async with self._semaphore:
            await self._process_task(task)

    async def _queue_processor(self) -> None:
        logger.info(_("Queue processor loop started"))
        while self._running:
            try:
                async with self._lock:
                    task = await self._get_next_task()
                if task:
                    logger.info(
                        _("DEBUG: Got task %s from queue, creating process task"),
                        task.id,
                    )
                    asyncio.create_task(self._process_task_with_semaphore(task))
                else:
                    # Log queue status periodically
                    pass
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(_("Queue processor error: %s"), exc)
                await asyncio.sleep(1)
        logger.info(_("Queue processor loop stopped"))


# ------------------------------------------------------------------
# Singleton helpers
# ------------------------------------------------------------------

_manager: Optional[QueueManager] = None


def get_queue_manager() -> QueueManager:
    global _manager
    if _manager is None:
        import logging
        logger = logging.getLogger(__name__)
        from i18n import _
        _manager = QueueManager()
        logger.info(_("DEBUG: Created new QueueManager instance (id=%s)"), id(_manager))
    return _manager


def set_queue_manager(manager: QueueManager) -> None:
    global _manager
    _manager = manager
