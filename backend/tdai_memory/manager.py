from __future__ import annotations

import asyncio
import logging

import openai

from backend.tdai_memory.capture import perform_auto_capture
from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.models import (
    CaptureResult,
    CompletedTurn,
    ConversationSearchParams,
    MemorySearchParams,
    RecallResult,
    SearchResult,
)
from backend.tdai_memory.offload.manager import OffloadManager
from backend.tdai_memory.pipeline.l3_profile import bootstrap_agent_profile, set_identity_seed
from backend.tdai_memory.pipeline.scheduler import PipelineScheduler
from backend.tdai_memory.recall import perform_auto_recall
from backend.tdai_memory.search import search_conversations, search_memories
from backend.tdai_memory.store.embedding import EmbeddingService
from backend.tdai_memory.store.postgres import PostgresStore
from backend.tdai_memory.store.qdrant import QdrantStore

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(
        self, config: MemoryConfig, openai_client: openai.AsyncOpenAI | None = None
    ) -> None:
        self.config = config
        self._user_client = openai_client
        self._client: openai.AsyncOpenAI | None = None

        self._postgres: PostgresStore | None = None
        self._qdrant: QdrantStore | None = None
        self._embedding: EmbeddingService | None = None
        self._scheduler: PipelineScheduler | None = None
        self._offload: OffloadManager | None = None

        self._bg_tasks: set[asyncio.Task] = set()
        self._initialized = False

    async def initialize(self) -> None:
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
            self.config.qdrant_url, self._embedding.get_dimensions()
        )
        await self._qdrant.initialize()

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
        logger.info("MemoryManager initialized")

    async def destroy(self) -> None:
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()

        if self._scheduler is not None:
            await self._scheduler.stop()

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
        logger.info("MemoryManager destroyed")

    async def recall(
        self, *, agent_id: str, user_text: str, session_key: str
    ) -> RecallResult:
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
