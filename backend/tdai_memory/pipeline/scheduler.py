from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import openai

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.models import PipelineSessionState
from backend.tdai_memory.store.embedding import EmbeddingService
from backend.tdai_memory.store.postgres import PostgresStore
from backend.tdai_memory.store.qdrant import QdrantStore

from .l1_extraction import run_l1_extraction
from .l2_scenes import run_l2_scene_grouping
from .l3_profile import run_l3_profile_generation

logger = logging.getLogger(__name__)


class PipelineScheduler:
    def __init__(
        self,
        postgres: PostgresStore,
        qdrant: QdrantStore,
        embedding: EmbeddingService,
        llm_client: openai.AsyncOpenAI,
        config: MemoryConfig,
        data_dir: str,
    ) -> None:
        self._postgres = postgres
        self._qdrant = qdrant
        self._embedding = embedding
        self._llm_client = llm_client
        self._config = config
        self._data_dir = data_dir

        self._timers: dict[tuple[str, str], asyncio.Task] = {}
        self._gc_task: asyncio.Task | None = None
        self._l2_timers: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self._gc_task = asyncio.create_task(self._gc_loop())
        logger.info("PipelineScheduler started")

    async def stop(self) -> None:
        for key in list(self._timers.keys()):
            self._timers[key].cancel()
        self._timers.clear()
        for key in list(self._l2_timers.keys()):
            self._l2_timers[key].cancel()
        self._l2_timers.clear()
        if self._gc_task is not None:
            self._gc_task.cancel()
            try:
                await self._gc_task
            except asyncio.CancelledError:
                pass
            self._gc_task = None
        logger.info("PipelineScheduler stopped")

    async def notify_conversation(self, agent_id: str, session_key: str) -> None:
        state = await self._postgres.read_pipeline_state(agent_id, session_key)
        if state is None:
            state = PipelineSessionState(
                agent_id=agent_id,
                session_key=session_key,
            )

        state.conversation_count += 1
        now_ms = int(time.time() * 1000)
        state.last_active_time = now_ms

        effective_threshold = self._config.pipeline.every_n_conversations
        if self._config.pipeline.enable_warmup and state.warmup_threshold > 0:
            effective_threshold = state.warmup_threshold

        if state.conversation_count >= effective_threshold:
            await self._trigger_l1(agent_id, session_key)
        else:
            self._schedule_idle_timeout(agent_id, session_key)

        await self._postgres.write_pipeline_state(state)

    async def _trigger_l1(self, agent_id: str, session_key: str) -> None:
        key = (agent_id, session_key)
        if key in self._timers:
            self._timers[key].cancel()
            del self._timers[key]

        logger.info(
            "Triggering L1 extraction for agent=%s session=%s",
            agent_id,
            session_key,
        )

        state = await self._postgres.read_pipeline_state(agent_id, session_key)
        checkpoint_cursor = state.last_extraction_updated_time if state else None

        try:
            await run_l1_extraction(
                agent_id=agent_id,
                session_key=session_key,
                postgres=self._postgres,
                qdrant=self._qdrant,
                embedding=self._embedding,
                llm_client=self._llm_client,
                config=self._config,
                data_dir=self._data_dir,
                checkpoint_cursor=checkpoint_cursor,
            )
        except Exception:
            logger.exception(
                "L1 extraction failed for agent=%s session=%s",
                agent_id,
                session_key,
            )
            return

        state = await self._postgres.read_pipeline_state(agent_id, session_key)
        if state is None:
            state = PipelineSessionState(
                agent_id=agent_id,
                session_key=session_key,
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        state.conversation_count = 0
        state.last_extraction_time = now_iso
        state.last_extraction_updated_time = now_iso

        if self._config.pipeline.enable_warmup and state.warmup_threshold > 0:
            if state.warmup_threshold < self._config.pipeline.every_n_conversations:
                state.warmup_threshold *= 2
            else:
                state.warmup_threshold = 0

        state.l2_pending_l1_count += 1
        await self._postgres.write_pipeline_state(state)

        await self._evaluate_l2(agent_id)

    async def _evaluate_l2(self, agent_id: str) -> None:
        states = await self._get_all_pipeline_states_for_agent(agent_id)
        total_pending = sum(s.l2_pending_l1_count for s in states)

        if total_pending < 3:
            return

        if agent_id in self._l2_timers:
            return

        l2_last = None
        for s in states:
            if s.l2_last_extraction_time:
                if l2_last is None or s.l2_last_extraction_time > l2_last:
                    l2_last = s.l2_last_extraction_time

        if l2_last:
            try:
                last_dt = datetime.fromisoformat(l2_last)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            except (ValueError, TypeError):
                elapsed = float("inf")
            if elapsed < self._config.pipeline.l2_min_interval_seconds:
                return
            if elapsed >= self._config.pipeline.l2_max_interval_seconds:
                pass
        else:
            pass

        delay = self._config.pipeline.l2_delay_after_l1_seconds
        self._l2_timers[agent_id] = asyncio.create_task(
            self._l2_delay_task(agent_id, delay)
        )

    async def _l2_delay_task(self, agent_id: str, delay: int) -> None:
        await asyncio.sleep(delay)
        self._l2_timers.pop(agent_id, None)
        await self._trigger_l2(agent_id)

    async def _trigger_l2(self, agent_id: str) -> None:
        logger.info("Triggering L2 scene grouping for agent=%s", agent_id)

        try:
            await run_l2_scene_grouping(
                agent_id=agent_id,
                postgres=self._postgres,
                llm_client=self._llm_client,
                config=self._config,
                data_dir=self._data_dir,
            )
        except Exception:
            logger.exception("L2 scene grouping failed for agent=%s", agent_id)
            return

        states = await self._get_all_pipeline_states_for_agent(agent_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        for s in states:
            s.l2_pending_l1_count = 0
            s.l2_last_extraction_time = now_iso
            await self._postgres.write_pipeline_state(s)

        l1_count = await self._postgres.count_l1(agent_id)
        if l1_count >= self._config.persona.trigger_every_n:
            l3_meta_key = f"l3_last_gen_count_{agent_id}"
            last_gen_val = await self._postgres.get_embedding_meta(
                agent_id, l3_meta_key
            )
            last_gen_count = int(last_gen_val) if last_gen_val else 0
            if l1_count - last_gen_count >= self._config.persona.trigger_every_n:
                await self._trigger_l3(agent_id)

    async def _trigger_l3(self, agent_id: str) -> None:
        logger.info("Triggering L3 profile generation for agent=%s", agent_id)

        try:
            await run_l3_profile_generation(
                agent_id=agent_id,
                postgres=self._postgres,
                llm_client=self._llm_client,
                config=self._config,
                data_dir=self._data_dir,
                trigger_reason="达到阈值",
            )
        except Exception:
            logger.exception("L3 profile generation failed for agent=%s", agent_id)
            return

        l1_count = await self._postgres.count_l1(agent_id)
        l3_meta_key = f"l3_last_gen_count_{agent_id}"
        await self._postgres.set_embedding_meta(
            agent_id, l3_meta_key, str(l1_count)
        )

    async def flush_session(self, agent_id: str, session_key: str) -> None:
        state = await self._postgres.read_pipeline_state(agent_id, session_key)
        if state is not None and state.conversation_count > 0:
            await self._trigger_l1(agent_id, session_key)

    def _schedule_idle_timeout(self, agent_id: str, session_key: str) -> None:
        key = (agent_id, session_key)
        if key in self._timers:
            self._timers[key].cancel()
        self._timers[key] = asyncio.create_task(
            self._idle_timeout_task(agent_id, session_key)
        )

    async def _idle_timeout_task(
        self, agent_id: str, session_key: str
    ) -> None:
        await asyncio.sleep(self._config.pipeline.l1_idle_timeout_seconds)

        key = (agent_id, session_key)
        state = await self._postgres.read_pipeline_state(agent_id, session_key)
        if state is None or state.conversation_count <= 0:
            self._timers.pop(key, None)
            return

        now_ms = int(time.time() * 1000)
        idle_ms = self._config.pipeline.l1_idle_timeout_seconds * 1000
        if state.last_active_time + idle_ms < now_ms:
            await self._trigger_l1(agent_id, session_key)

        self._timers.pop(key, None)

    async def _gc_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(3600)
                await self._collect_garbage()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("GC loop error")

    async def _collect_garbage(self) -> None:
        now_ms = int(time.time() * 1000)
        window_ms = self._config.pipeline.session_active_window_hours * 3600 * 1000
        cutoff_ms = now_ms - window_ms

        pool = self._postgres._pool
        if pool is None:
            return

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT agent_id, session_key, last_active_time FROM pipeline_state"
            )

        stale_keys: list[tuple[str, str]] = []
        for row in rows:
            if row["last_active_time"] < cutoff_ms:
                stale_keys.append((row["agent_id"], row["session_key"]))

        if stale_keys:
            async with pool.acquire() as conn:
                for agent_id, session_key in stale_keys:
                    await conn.execute(
                        "DELETE FROM pipeline_state WHERE agent_id = $1 AND session_key = $2",
                        agent_id,
                        session_key,
                    )
            logger.info(
                "Pipeline GC cleaned %d stale sessions",
                len(stale_keys),
            )

    async def _get_all_pipeline_states_for_agent(
        self, agent_id: str
    ) -> list[PipelineSessionState]:
        pool = self._postgres._pool
        if pool is None:
            return []

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_id, session_key, conversation_count,
                       last_extraction_time, last_extraction_updated_time,
                       last_active_time, l2_pending_l1_count, warmup_threshold,
                       l2_last_extraction_time
                FROM pipeline_state
                WHERE agent_id = $1
                """,
                agent_id,
            )
        return [PipelineSessionState(**dict(row)) for row in rows]
