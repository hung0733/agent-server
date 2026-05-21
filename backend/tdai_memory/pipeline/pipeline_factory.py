from __future__ import annotations

import asyncio
import logging
import os

import openai

from ..config import MemoryConfig
from ..store.embedding import EmbeddingService
from ..store.postgres import PostgresStore
from ..store.qdrant import QdrantStore
from .scheduler import PipelineScheduler

logger = logging.getLogger(__name__)

_DIRS = [
    "conversations",
    "records",
    "scene_blocks",
    ".metadata",
    ".backup",
]


async def create_pipeline(
    config: MemoryConfig,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    llm_client: openai.AsyncOpenAI,
    data_dir: str,
) -> PipelineScheduler:
    scheduler = PipelineScheduler(
        postgres=postgres,
        qdrant=qdrant,
        embedding=embedding,
        llm_client=llm_client,
        config=config,
        data_dir=data_dir,
    )
    await scheduler.start()
    return scheduler


async def init_data_directories(agent_id: str, data_dir: str) -> None:
    agent_dir = os.path.join(data_dir, agent_id)

    def _mkdirs() -> None:
        for subdir in _DIRS:
            os.makedirs(os.path.join(agent_dir, subdir), exist_ok=True)

    await asyncio.to_thread(_mkdirs)
