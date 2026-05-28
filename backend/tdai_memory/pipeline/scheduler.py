from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import openai

from backend.i18n import t
from ..config import MemoryConfig
from ..models import PipelineSessionState
from ..store.embedding import EmbeddingService
from ..store.postgres import PostgresStore
from ..store.qdrant import QdrantStore
from .l1_extraction import run_l1_extraction
from .l2_scenes import run_l2_scene_grouping
from .l3_profile import run_l3_profile_generation
from .metrics import report_metric

logger = logging.getLogger(__name__)

L1_MAX_RETRIES = 5
L1_RETRY_DELAY = 30.0
L2_MIN_L1_COUNT = 3
_GC_MULTIPLIER = 3


class SerialQueue:
    def __init__(self, label: str) -> None:
        self._label = label
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._queue = asyncio.Queue()
        self._running = True
        self._worker = asyncio.create_task(self._process())

    async def stop(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    async def enqueue(self, coro_factory, *args):
        if self._queue is not None and self._running:
            await self._queue.put((coro_factory, args))

    async def _process(self) -> None:
        while self._running:
            try:
                item = await self._queue.get()
            except (asyncio.CancelledError, RuntimeError):
                return
            if item is None:
                self._queue.task_done()
                return
            coro_factory, args = item
            try:
                await coro_factory(*args)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(t("tdai_memory.pipeline.serial_queue_task_failed"), self._label)
            finally:
                self._queue.task_done()


class PipelineScheduler:
    def __init__(
        self,
        postgres: PostgresStore,
        qdrant: QdrantStore,
        embedding: EmbeddingService,
        llm_client: openai.AsyncOpenAI,
        config: MemoryConfig,
        data_dir: str,
        on_l1_complete: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._postgres = postgres
        self._qdrant = qdrant
        self._embedding = embedding
        self._llm_client = llm_client
        self._config = config
        self._data_dir = data_dir
        self._on_l1_complete = on_l1_complete

        self._sessions: dict[tuple[str, str], PipelineSessionState] = {}
        self._idle_timers: dict[tuple[str, str], asyncio.Task] = {}
        self._l2_timers: dict[str, asyncio.Task] = {}
        self._l1_queue = SerialQueue("L1")
        self._l2_queue = SerialQueue("L2")
        self._l3_queue = SerialQueue("L3")

        self._gc_task: asyncio.Task | None = None
        self._running = False

        self._l1_queued: dict[tuple[str, str], bool] = {}
        self._l2_queued: bool = False
        self._l3_running: bool = False
        self._l3_pending: bool = False

    async def start(self, restored_states: list[PipelineSessionState] | None = None) -> None:
        await self._l1_queue.start()
        await self._l2_queue.start()
        await self._l3_queue.start()

        if restored_states:
            for state in restored_states:
                key = (state.agent_id, state.session_key)
                self._sessions[key] = state
                if state.conversation_count > 0:
                    self._schedule_idle_timeout(state.agent_id, state.session_key)

        self._running = True
        self._gc_task = asyncio.create_task(self._gc_loop())

        for agent_id in {s.agent_id for s in self._sessions.values()}:
            self._maybe_schedule_l2(agent_id)

        logger.info(t("tdai_memory.pipeline.scheduler_started"), len(self._sessions))

    async def stop(self) -> None:
        self._running = False

        flush_tasks = []
        for key, state in list(self._sessions.items()):
            if state.conversation_count > 0:
                flush_tasks.append(
                    self.flush_session(key[0], key[1])
                )
        if flush_tasks:
            await asyncio.wait(flush_tasks, timeout=2.0)

        for key, task in list(self._idle_timers.items()):
            task.cancel()
        self._idle_timers.clear()

        for key, task in list(self._l2_timers.items()):
            task.cancel()
        self._l2_timers.clear()

        if self._gc_task is not None:
            self._gc_task.cancel()
            try:
                await self._gc_task
            except asyncio.CancelledError:
                pass

        await self._l1_queue.stop()
        await self._l2_queue.stop()
        await self._l3_queue.stop()
        logger.info(t("tdai_memory.pipeline.scheduler_stopped"))

    async def notify_conversation(self, agent_id: str, session_key: str) -> None:
        key = (agent_id, session_key)

        try:
            state = await self._postgres.read_pipeline_state(agent_id, session_key)
        except Exception:
            logger.exception(t("tdai_memory.pipeline.read_pipeline_state_failed"), agent_id, session_key)
            return

        if state is None:
            state = PipelineSessionState(
                agent_id=agent_id,
                session_key=session_key,
                warmup_threshold=1,
            )
        else:
            state.agent_id = agent_id
            state.session_key = session_key

        state.conversation_count += 1
        state.last_active_time = int(datetime.now(timezone.utc).timestamp() * 1000)

        effective_threshold = (
            state.warmup_threshold
            if self._config.pipeline.enable_warmup and state.warmup_threshold > 0
            else self._config.pipeline.every_n_conversations
        )

        if state.conversation_count >= effective_threshold:
            self._cancel_idle_timer(key)
            await self._l1_queue.enqueue(self._trigger_l1, agent_id, session_key, state)
        else:
            self._schedule_idle_timeout(agent_id, session_key)

        self._sessions[key] = state
        try:
            await self._postgres.write_pipeline_state(state)
        except Exception:
            logger.exception(t("tdai_memory.pipeline.write_pipeline_state_failed"), agent_id, session_key)

    async def flush_session(self, agent_id: str, session_key: str) -> None:
        key = (agent_id, session_key)
        state = self._sessions.get(key)
        if state is None:
            try:
                state = await self._postgres.read_pipeline_state(agent_id, session_key)
            except Exception:
                return

        if state and state.conversation_count > 0:
            self._cancel_idle_timer(key)
            await self._l1_queue.enqueue(self._trigger_l1, agent_id, session_key, state)

    def _schedule_idle_timeout(self, agent_id: str, session_key: str) -> None:
        key = (agent_id, session_key)
        if key in self._idle_timers:
            return
        task = asyncio.create_task(
            self._idle_timeout_task(agent_id, session_key)
        )
        self._idle_timers[key] = task

    def _cancel_idle_timer(self, key: tuple[str, str]) -> None:
        task = self._idle_timers.pop(key, None)
        if task is not None:
            task.cancel()

    async def _idle_timeout_task(self, agent_id: str, session_key: str) -> None:
        timeout_s = self._config.pipeline.l1_idle_timeout_seconds
        try:
            await asyncio.sleep(timeout_s)
        except asyncio.CancelledError:
            return

        key = (agent_id, session_key)
        state = self._sessions.get(key)
        if state is None:
            return

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if now_ms - state.last_active_time >= timeout_s * 1000 and state.conversation_count > 0:
            self._idle_timers.pop(key, None)
            await self._l1_queue.enqueue(self._trigger_l1, agent_id, session_key, state)

    async def _trigger_l1(self, agent_id: str, session_key: str, state: PipelineSessionState) -> None:
        key = (agent_id, session_key)
        if self._l1_queued.pop(key, False):
            return
        self._l1_queued[key] = True
        self._cancel_idle_timer(key)

        for attempt in range(1, L1_MAX_RETRIES + 1):
            try:
                logger.info(
                    t("tdai_memory.pipeline.l1_extraction_started"),
                    agent_id, session_key, attempt, L1_MAX_RETRIES, state.conversation_count,
                )
                await run_l1_extraction(
                    agent_id=agent_id,
                    session_key=session_key,
                    postgres=self._postgres,
                    qdrant=self._qdrant,
                    embedding=self._embedding,
                    llm_client=self._llm_client,
                    config=self._config,
                    data_dir=self._data_dir,
                )
                break
            except Exception:
                logger.exception(
                    t("tdai_memory.pipeline.l1_extraction_failed"), agent_id, session_key, attempt
                )
                if attempt < L1_MAX_RETRIES:
                    await asyncio.sleep(L1_RETRY_DELAY)
                else:
                    self._l1_queued.pop(key, None)
                    return

        self._l1_queued.pop(key, None)

        now_iso = datetime.now(timezone.utc).isoformat()
        pre_reset_count = state.conversation_count
        state.conversation_count = 0
        state.last_extraction_time = now_iso
        state.last_extraction_updated_time = now_iso
        state.l2_pending_l1_count = (state.l2_pending_l1_count or 0) + 1

        report_metric("pipeline_l1_trigger", {
            "agent_id": agent_id,
            "session_key": session_key,
            "conversation_count_before_reset": pre_reset_count,
            "l1_extraction_time": now_iso,
        })

        if self._config.pipeline.enable_warmup:
            if state.warmup_threshold > 0:
                next_threshold = state.warmup_threshold * 2
                if next_threshold >= self._config.pipeline.every_n_conversations:
                    state.warmup_threshold = 0
                else:
                    state.warmup_threshold = next_threshold

        self._sessions[key] = state
        try:
            await self._postgres.write_pipeline_state(state)
        except Exception:
            logger.exception(t("tdai_memory.pipeline.write_pipeline_state_after_l1_failed"), agent_id, session_key)

        if self._on_l1_complete is not None:
            try:
                await self._on_l1_complete(agent_id, session_key)
            except Exception:
                logger.exception(
                    t("tdai_memory.pipeline.timeline_cache_invalidate_failed"),
                    agent_id,
                    session_key,
                )

        if state.l2_pending_l1_count >= L2_MIN_L1_COUNT:
            await self._l2_queue.enqueue(self._maybe_trigger_l2, agent_id)

    async def _maybe_trigger_l2(self, agent_id: str) -> None:
        now = int(datetime.now(timezone.utc).timestamp())
        delay = self._config.pipeline.l2_delay_after_l1_seconds
        desired = now + delay
        min_fire = now - self._config.pipeline.l2_min_interval_seconds

        existing = self._l2_timers.get(agent_id)
        if existing is not None:
            existing.cancel()
            self._l2_timers.pop(agent_id, None)

        fire_at = max(desired, min_fire)
        wait_seconds = max(0, fire_at - now)
        await asyncio.sleep(wait_seconds)

        await self._trigger_l2(agent_id)
        self._schedule_l2_max_interval(agent_id)

    def _schedule_l2_max_interval(self, agent_id: str) -> None:
        existing = self._l2_timers.pop(agent_id, None)
        if existing is not None:
            existing.cancel()

        max_interval = self._config.pipeline.l2_max_interval_seconds
        task = asyncio.create_task(self._l2_max_interval_task(agent_id))
        self._l2_timers[agent_id] = task

    async def _l2_max_interval_task(self, agent_id: str) -> None:
        try:
            await asyncio.sleep(self._config.pipeline.l2_max_interval_seconds)
        except asyncio.CancelledError:
            return
        await self._l2_queue.enqueue(self._trigger_l2_from_timer, agent_id)

    async def _trigger_l2_from_timer(self, agent_id: str) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        active_window_ms = self._config.pipeline.session_active_window_hours * 3600 * 1000

        has_active = False
        for (aid, _), state in self._sessions.items():
            if aid == agent_id and (now_ms - state.last_active_time) < active_window_ms:
                has_active = True
                break

        if not has_active:
            logger.info(t("tdai_memory.pipeline.skipping_l2_no_active_sessions"), agent_id)
            self._schedule_l2_max_interval(agent_id)
            return

        await self._trigger_l2(agent_id)
        self._schedule_l2_max_interval(agent_id)

    async def _trigger_l2(self, agent_id: str) -> None:
        try:
            logger.info(t("tdai_memory.pipeline.l2_scene_grouping_started"), agent_id)
            await run_l2_scene_grouping(
                agent_id=agent_id,
                postgres=self._postgres,
                llm_client=self._llm_client,
                config=self._config,
                data_dir=self._data_dir,
            )
        except Exception:
            logger.exception(t("tdai_memory.pipeline.l2_scene_grouping_failed"), agent_id)
            return

        for (aid, sk), state in list(self._sessions.items()):
            if aid == agent_id and state.l2_pending_l1_count:
                state.l2_pending_l1_count = 0
                state.l2_last_extraction_time = datetime.now(timezone.utc).isoformat()
                try:
                    await self._postgres.write_pipeline_state(state)
                except Exception:
                    pass

        await self._maybe_trigger_l3(agent_id)

    async def _maybe_trigger_l3(self, agent_id: str) -> None:
        if self._l3_running:
            self._l3_pending = True
            return
        await self._l3_queue.enqueue(self._trigger_l3, agent_id)

    async def _trigger_l3(self, agent_id: str) -> None:
        if self._l3_running:
            self._l3_pending = True
            return

        self._l3_running = True
        self._l3_pending = False

        try:
            l1_count = await self._postgres.count_l1(agent_id)
        except Exception:
            logger.exception(t("tdai_memory.pipeline.count_l1_failed"), agent_id)
            l1_count = 0

        try:
            logger.info(t("tdai_memory.pipeline.l3_profile_generation_started"), agent_id)
            await run_l3_profile_generation(
                agent_id=agent_id,
                postgres=self._postgres,
                llm_client=self._llm_client,
                config=self._config,
                data_dir=self._data_dir,
                trigger_reason=f"Post-L2 trigger (L1 count: {l1_count})",
            )
            report_metric("l3_persona_generation", {
                "agent_id": agent_id,
                "l1_count": l1_count,
                "trigger_reason": f"Post-L2 trigger (L1 count: {l1_count})",
            })
        except Exception:
            logger.exception(t("tdai_memory.pipeline.l3_profile_generation_failed"), agent_id)
        finally:
            self._l3_running = False

        if self._l3_pending:
            self._l3_pending = False
            try:
                await self._l3_queue.enqueue(self._trigger_l3, agent_id)
            except Exception:
                logger.exception(t("tdai_memory.pipeline.enqueue_pending_l3_failed"), agent_id)

    async def _gc_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return

            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            active_window_ms = self._config.pipeline.session_active_window_hours * 3600 * 1000 * _GC_MULTIPLIER

            stale_keys = []
            for key, state in self._sessions.items():
                if (now_ms - state.last_active_time) >= active_window_ms:
                    stale_keys.append(key)

            for key in stale_keys:
                self._cancel_idle_timer(key)
                self._sessions.pop(key, None)

            if stale_keys:
                logger.info(t("tdai_memory.pipeline.gc_evicted_stale_sessions"), len(stale_keys))

    def get_session_state(self, agent_id: str, session_key: str) -> PipelineSessionState | None:
        return self._sessions.get((agent_id, session_key))

    def get_session_keys(self) -> list[tuple[str, str]]:
        return list(self._sessions.keys())

    def get_queue_sizes(self) -> dict[str, int]:
        sizes = {"l1": 0, "l2": 0, "l3": 0}
        for name, q in [("l1", self._l1_queue), ("l2", self._l2_queue), ("l3", self._l3_queue)]:
            if q._queue is not None:
                sizes[name] = q._queue.qsize()
        return sizes
