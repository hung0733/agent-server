from __future__ import annotations

import asyncio
import logging
from os import getenv
import time
from typing import Any, Callable

import openai

from backend.i18n import t
from .capture import perform_auto_capture
from .config import MemoryConfig, normalize_config
from .models import (
    CaptureResult,
    CompletedTurn,
    ConversationSearchParams,
    MemorySearchParams,
    RecallResult,
    SearchResult,
)
from .offload.manager import OffloadManager
from .pipeline.l3_profile import bootstrap_agent_profile, set_identity_seed
from .pipeline.memory_cleaner import MemoryCleaner
from .pipeline.scheduler import PipelineScheduler
from .recall import perform_auto_recall
from .search import search_conversations, search_memories
from .store.embedding import EmbeddingService
from .store.postgres import PostgresStore
from .store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_init_cache: dict[str, asyncio.Event] = {}
_init_lock = asyncio.Lock()


def _env_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(t("tdai_memory.manager.invalid_boolean_env") % name)


def _env_optional_str(_: str, value: str) -> str | None:
    if value == "":
        return None
    return value


def _apply_env(
    target: Any,
    attr: str,
    env_name: str,
    cast: Callable[[str], Any] | Callable[[str, str], Any] = str,
) -> None:
    value = getenv(env_name)
    if value is None:
        return

    try:
        parsed_value = cast(value)
    except TypeError:
        parsed_value = cast(env_name, value)
    setattr(target, attr, parsed_value)


class MemoryManager:
    @staticmethod
    def from_env() -> MemoryConfig:
        config = MemoryConfig()

        _apply_env(config, "postgres_url", "TDAI_MEM_POSTGRES_URL")
        _apply_env(config, "postgres_schema", "TDAI_MEM_POSTGRES_SCHEMA")
        _apply_env(config, "qdrant_url", "TDAI_MEM_QDRANT_URL")
        _apply_env(config, "qdrant_l0_collection", "TDAI_MEM_QDRANT_L0_COLLECTION")
        _apply_env(config, "qdrant_l1_collection", "TDAI_MEM_QDRANT_L1_COLLECTION")
        _apply_env(config, "data_dir", "TDAI_MEM_DATA_DIR")

        _apply_env(config.embedding, "api_key", "TDAI_MEM_EMBEDDING_API_KEY")
        _apply_env(config.embedding, "base_url", "TDAI_MEM_EMBEDDING_BASE_URL")
        _apply_env(config.embedding, "model", "TDAI_MEM_EMBEDDING_MODEL")
        _apply_env(config.embedding, "dimensions", "TDAI_MEM_EMBEDDING_DIMENSIONS", int)
        _apply_env(
            config.embedding,
            "max_input_chars",
            "TDAI_MEM_EMBEDDING_MAX_INPUT_CHARS",
            int,
        )
        _apply_env(config.embedding, "timeout_ms", "TDAI_MEM_EMBEDDING_TIMEOUT_MS", int)
        _apply_env(
            config.embedding,
            "conflict_recall_top_k",
            "TDAI_MEM_EMBEDDING_CONFLICT_RECALL_TOP_K",
            int,
        )
        _apply_env(
            config.embedding,
            "recall_timeout_ms",
            "TDAI_MEM_EMBEDDING_RECALL_TIMEOUT_MS",
            int,
        )
        _apply_env(
            config.embedding,
            "capture_timeout_ms",
            "TDAI_MEM_EMBEDDING_CAPTURE_TIMEOUT_MS",
            int,
        )

        _apply_env(config.capture, "enabled", "TDAI_MEM_CAPTURE_ENABLED", _env_bool)
        _apply_env(
            config.capture,
            "l0_l1_retention_days",
            "TDAI_MEM_CAPTURE_L0_L1_RETENTION_DAYS",
            int,
        )
        _apply_env(
            config.capture,
            "allow_aggressive_cleanup",
            "TDAI_MEM_CAPTURE_ALLOW_AGGRESSIVE_CLEANUP",
            _env_bool,
        )

        _apply_env(config.extraction, "enabled", "TDAI_MEM_EXTRACTION_ENABLED", _env_bool)
        _apply_env(
            config.extraction,
            "enable_dedup",
            "TDAI_MEM_EXTRACTION_ENABLE_DEDUP",
            _env_bool,
        )
        _apply_env(
            config.extraction,
            "max_memories_per_session",
            "TDAI_MEM_EXTRACTION_MAX_MEMORIES_PER_SESSION",
            int,
        )
        _apply_env(
            config.extraction,
            "model",
            "TDAI_MEM_EXTRACTION_MODEL",
            _env_optional_str,
        )

        _apply_env(config.persona, "trigger_every_n", "TDAI_MEM_PERSONA_TRIGGER_EVERY_N", int)
        _apply_env(config.persona, "max_scenes", "TDAI_MEM_PERSONA_MAX_SCENES", int)
        _apply_env(config.persona, "backup_count", "TDAI_MEM_PERSONA_BACKUP_COUNT", int)
        _apply_env(
            config.persona,
            "scene_backup_count",
            "TDAI_MEM_PERSONA_SCENE_BACKUP_COUNT",
            int,
        )
        _apply_env(config.persona, "model", "TDAI_MEM_PERSONA_MODEL", _env_optional_str)

        _apply_env(
            config.pipeline,
            "every_n_conversations",
            "TDAI_MEM_PIPELINE_EVERY_N_CONVERSATIONS",
            int,
        )
        _apply_env(
            config.pipeline,
            "enable_warmup",
            "TDAI_MEM_PIPELINE_ENABLE_WARMUP",
            _env_bool,
        )
        _apply_env(
            config.pipeline,
            "l1_idle_timeout_seconds",
            "TDAI_MEM_PIPELINE_L1_IDLE_TIMEOUT_SECONDS",
            int,
        )
        _apply_env(
            config.pipeline,
            "l2_delay_after_l1_seconds",
            "TDAI_MEM_PIPELINE_L2_DELAY_AFTER_L1_SECONDS",
            int,
        )
        _apply_env(
            config.pipeline,
            "l2_min_interval_seconds",
            "TDAI_MEM_PIPELINE_L2_MIN_INTERVAL_SECONDS",
            int,
        )
        _apply_env(
            config.pipeline,
            "l2_max_interval_seconds",
            "TDAI_MEM_PIPELINE_L2_MAX_INTERVAL_SECONDS",
            int,
        )
        _apply_env(
            config.pipeline,
            "session_active_window_hours",
            "TDAI_MEM_PIPELINE_SESSION_ACTIVE_WINDOW_HOURS",
            int,
        )

        _apply_env(config.recall, "enabled", "TDAI_MEM_RECALL_ENABLED", _env_bool)
        _apply_env(config.recall, "max_results", "TDAI_MEM_RECALL_MAX_RESULTS", int)
        _apply_env(config.recall, "score_threshold", "TDAI_MEM_RECALL_SCORE_THRESHOLD", float)
        _apply_env(config.recall, "strategy", "TDAI_MEM_RECALL_STRATEGY")
        _apply_env(config.recall, "timeout_ms", "TDAI_MEM_RECALL_TIMEOUT_MS", int)

        _apply_env(config.bm25, "enabled", "TDAI_MEM_BM25_ENABLED", _env_bool)
        _apply_env(config.bm25, "language", "TDAI_MEM_BM25_LANGUAGE")

        _apply_env(config.llm, "enabled", "TDAI_MEM_LLM_ENABLED", _env_bool)
        _apply_env(config.llm, "model", "TDAI_MEM_LLM_MODEL")
        _apply_env(config.llm, "base_url", "TDAI_MEM_LLM_BASE_URL")
        _apply_env(config.llm, "api_key", "TDAI_MEM_LLM_API_KEY")
        _apply_env(config.llm, "max_tokens", "TDAI_MEM_LLM_MAX_TOKENS", int)
        _apply_env(config.llm, "timeout_ms", "TDAI_MEM_LLM_TIMEOUT_MS", int)

        _apply_env(config.offload, "enabled", "TDAI_MEM_OFFLOAD_ENABLED", _env_bool)
        _apply_env(config.offload, "mode", "TDAI_MEM_OFFLOAD_MODE")
        _apply_env(config.offload, "model", "TDAI_MEM_OFFLOAD_MODEL", _env_optional_str)
        _apply_env(config.offload, "temperature", "TDAI_MEM_OFFLOAD_TEMPERATURE", float)
        _apply_env(
            config.offload,
            "force_trigger_threshold",
            "TDAI_MEM_OFFLOAD_FORCE_TRIGGER_THRESHOLD",
            int,
        )
        _apply_env(config.offload, "data_dir", "TDAI_MEM_OFFLOAD_DATA_DIR", _env_optional_str)
        _apply_env(
            config.offload,
            "default_context_window",
            "TDAI_MEM_OFFLOAD_DEFAULT_CONTEXT_WINDOW",
            int,
        )
        _apply_env(
            config.offload,
            "max_pairs_per_batch",
            "TDAI_MEM_OFFLOAD_MAX_PAIRS_PER_BATCH",
            int,
        )
        _apply_env(config.offload, "l2_null_threshold", "TDAI_MEM_OFFLOAD_L2_NULL_THRESHOLD", int)
        _apply_env(config.offload, "l2_timeout_seconds", "TDAI_MEM_OFFLOAD_L2_TIMEOUT_SECONDS", int)
        _apply_env(config.offload, "mild_offload_ratio", "TDAI_MEM_OFFLOAD_MILD_OFFLOAD_RATIO", float)
        _apply_env(
            config.offload,
            "aggressive_compress_ratio",
            "TDAI_MEM_OFFLOAD_AGGRESSIVE_COMPRESS_RATIO",
            float,
        )
        _apply_env(config.offload, "mmd_max_token_ratio", "TDAI_MEM_OFFLOAD_MMD_MAX_TOKEN_RATIO", float)
        _apply_env(
            config.offload,
            "offload_retention_days",
            "TDAI_MEM_OFFLOAD_RETENTION_DAYS",
            int,
        )
        _apply_env(
            config.offload,
            "backend_url",
            "TDAI_MEM_OFFLOAD_BACKEND_URL",
            _env_optional_str,
        )
        _apply_env(config.offload, "backend_api_key", "TDAI_MEM_OFFLOAD_BACKEND_API_KEY")
        _apply_env(
            config.offload,
            "backend_timeout_ms",
            "TDAI_MEM_OFFLOAD_BACKEND_TIMEOUT_MS",
            int,
        )
        _apply_env(config.offload, "log_max_size_mb", "TDAI_MEM_OFFLOAD_LOG_MAX_SIZE_MB", int)
        _apply_env(config.offload, "user_id", "TDAI_MEM_OFFLOAD_USER_ID", _env_optional_str)
        _apply_env(
            config.offload,
            "mild_offload_scan_ratio",
            "TDAI_MEM_OFFLOAD_MILD_OFFLOAD_SCAN_RATIO",
            float,
        )
        _apply_env(
            config.offload,
            "aggressive_delete_ratio",
            "TDAI_MEM_OFFLOAD_AGGRESSIVE_DELETE_RATIO",
            float,
        )
        _apply_env(
            config.offload,
            "emergency_compress_ratio",
            "TDAI_MEM_OFFLOAD_EMERGENCY_COMPRESS_RATIO",
            float,
        )
        _apply_env(
            config.offload,
            "emergency_target_ratio",
            "TDAI_MEM_OFFLOAD_EMERGENCY_TARGET_RATIO",
            float,
        )

        return normalize_config(config)

    def __init__(
        self, config: MemoryConfig, openai_client: openai.AsyncOpenAI | None = None
    ) -> None:
        self.config = config
        self._user_client = openai_client
        self._client: openai.AsyncOpenAI | None = None
        self._instance_id: str | None = None

        self._postgres: PostgresStore | None = None
        self._qdrant: QdrantStore | None = None
        self._embedding: EmbeddingService | None = None
        self._scheduler: PipelineScheduler | None = None
        self._offload: OffloadManager | None = None
        self._cleaner: MemoryCleaner | None = None

        self._store_ready = asyncio.Event()
        self._bg_tasks: set[asyncio.Task] = set()
        self._initialized = False

    async def initialize(self) -> None:
        cache_key = self.config.data_dir

        async with _init_lock:
            if cache_key in _init_cache:
                event = _init_cache[cache_key]
            else:
                event = asyncio.Event()
                _init_cache[cache_key] = event

        if cache_key in _init_cache and _init_cache[cache_key] is not event:
            await event.wait()
            return

        try:
            if self._user_client is not None:
                self._client = self._user_client
            else:
                llm_cfg = self.config.llm
                self._client = openai.AsyncOpenAI(
                    api_key=llm_cfg.api_key,
                    base_url=llm_cfg.base_url,
                    timeout=(
                        llm_cfg.timeout_ms / 1000.0
                        if llm_cfg.timeout_ms > 0
                        else 30.0
                    ),
                )

            self._embedding = EmbeddingService(self.config.embedding)

            self._postgres = PostgresStore(self.config.postgres_url, self.config.postgres_schema)
            await self._postgres.initialize()

            self._qdrant = QdrantStore(
                self.config.qdrant_url,
                self._embedding.get_dimensions(),
                l0_collection=self.config.qdrant_l0_collection,
                l1_collection=self.config.qdrant_l1_collection,
            )
            await self._qdrant.initialize()

            self._store_ready.set()

            self._scheduler = PipelineScheduler(
                postgres=self._postgres,
                qdrant=self._qdrant,
                embedding=self._embedding,
                llm_client=self._client,
                config=self.config,
                data_dir=self.config.data_dir,
            )
            await self._scheduler.start()

            if self.config.offload.enabled:
                self._offload = OffloadManager(
                    data_dir=self.config.data_dir,
                    llm_client=self._client,
                    config=self.config,
                )

            self._initialized = True
            logger.info(t("tdai_memory.manager.initialized"))
        finally:
            event.set()

    async def destroy(self) -> None:
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            done, pending = await asyncio.wait(self._bg_tasks, timeout=5.0)
            for task in pending:
                task.cancel()
        self._bg_tasks.clear()

        if self._scheduler is not None:
            await self._scheduler.stop()

        if self._cleaner is not None:
            await self._cleaner.stop()

        if self._qdrant is not None:
            await self._qdrant.close()
        if self._postgres is not None:
            await self._postgres.close()
        if self._embedding is not None:
            await self._embedding.close()

        if self._client is not None and self._user_client is None:
            await self._client.close()
            self._client = None

        self._initialized = False
        _init_cache.pop(self.config.data_dir, None)
        logger.info(t("tdai_memory.manager.destroyed"))

    async def recall(
        self, *, agent_id: str, user_text: str, session_key: str
    ) -> RecallResult:
        await self._store_ready.wait()
        return await perform_auto_recall(
            agent_id=agent_id,
            user_text=user_text,
            session_key=session_key,
            postgres=self._postgres,
            qdrant=self._qdrant,
            embedding=self._embedding,
            data_dir=self.config.data_dir,
            config=self.config,
        )

    async def capture(
        self, *, agent_id: str, turn: CompletedTurn
    ) -> CaptureResult:
        await self._store_ready.wait()
        return await perform_auto_capture(
            turn=turn,
            agent_id=agent_id,
            postgres=self._postgres,
            qdrant=self._qdrant,
            embedding=self._embedding,
            data_dir=self.config.data_dir,
            on_scheduler_notify=(
                self._scheduler.notify_conversation
                if self._scheduler is not None
                else None
            ),
            bg_tasks=self._bg_tasks,
        )

    async def search_memories(
        self,
        *,
        agent_id: str,
        query: str,
        top_k: int = 5,
        strategy: str = "hybrid",
        score_threshold: float = 0.3,
        type_filter: str | None = None,
        scene_filter: str | None = None,
    ) -> SearchResult:
        params = MemorySearchParams(
            query=query,
            agent_id=agent_id,
            top_k=top_k,
            strategy=strategy,
            score_threshold=score_threshold,
            type_filter=type_filter,
            scene_filter=scene_filter,
        )
        return await search_memories(
            params, self._postgres, self._qdrant, self._embedding
        )

    async def search_conversations(
        self,
        *,
        agent_id: str,
        query: str,
        top_k: int = 5,
        session_key: str | None = None,
    ) -> SearchResult:
        params = ConversationSearchParams(
            query=query,
            agent_id=agent_id,
            top_k=top_k,
            session_key=session_key,
        )
        return await search_conversations(
            params, self._postgres, self._qdrant, self._embedding
        )

    async def end_session(self, *, agent_id: str, session_key: str) -> None:
        if self._scheduler is not None:
            await self._scheduler.flush_session(agent_id, session_key)

    async def set_identity_seed(self, *, agent_id: str, content: str) -> None:
        await set_identity_seed(agent_id, self.config.data_dir, content)

    async def bootstrap_agent(self, *, agent_id: str, prompt: str) -> dict[str, str]:
        return await bootstrap_agent_profile(
            agent_id=agent_id,
            data_dir=self.config.data_dir,
            llm_client=self._client,
            config=self.config,
            prompt=prompt,
        )

    async def seed(self, *, agent_id: str, sessions: list[dict], **kwargs) -> dict:
        from .pipeline.seed import seed_conversations

        return await seed_conversations(
            manager=self, agent_id=agent_id, sessions=sessions, **kwargs
        )

    def get_postgres(self) -> PostgresStore | None:
        return self._postgres

    def get_qdrant(self) -> QdrantStore | None:
        return self._qdrant

    def get_embedding(self) -> EmbeddingService | None:
        return self._embedding

    def get_scheduler(self) -> PipelineScheduler | None:
        return self._scheduler

    def get_offload(self) -> OffloadManager | None:
        return self._offload

    def is_scheduler_started(self) -> bool:
        return self._scheduler is not None and self._scheduler._running

    def set_instance_id(self, instance_id: str) -> None:
        self._instance_id = instance_id
