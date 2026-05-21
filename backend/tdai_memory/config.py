"""Configuration for the TDAI memory system — reads from agent-server .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CaptureConfig:
    """Auto-capture configuration."""

    enabled: bool = True
    l0_l1_retention_days: int = 0  # TTL in days, 0=disabled


@dataclass
class ExtractionConfig:
    """L1 memory extraction configuration."""

    enabled: bool = True
    enable_dedup: bool = True
    max_memories_per_session: int = 20
    model: str | None = None  # override LLM model for extraction


@dataclass
class PersonaConfig:
    """L3 persona/profile generation configuration."""

    trigger_every_n: int = 50  # new memories threshold for generation
    max_scenes: int = 15
    backup_count: int = 3  # persona backups
    scene_backup_count: int = 10  # scene block backups
    model: str | None = None  # override LLM model


@dataclass
class PipelineConfig:
    """Pipeline scheduler configuration."""

    every_n_conversations: int = 5  # trigger L1 after N conversations
    enable_warmup: bool = True  # exponential warmup 1→2→4→8→everyN
    l1_idle_timeout_seconds: int = 600  # idle timeout before L1
    l2_delay_after_l1_seconds: int = 90  # delay before L2 after L1
    l2_min_interval_seconds: int = 900  # min interval between L2 runs
    l2_max_interval_seconds: int = 3600  # max interval between L2 runs
    session_active_window_hours: int = 24  # inactive window for session GC


@dataclass
class RecallConfig:
    """Auto-recall configuration."""

    enabled: bool = True
    max_results: int = 5
    score_threshold: float = 0.3
    strategy: Literal["embedding", "keyword", "hybrid"] = "hybrid"
    timeout_ms: int = 5000


@dataclass
class EmbeddingConfig:
    """Embedding service configuration."""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"
    dimensions: int = 0  # 0 = model default (1536 for text-embedding-3-small)
    max_input_chars: int = 5000
    timeout_ms: int = 10000


@dataclass
class BM25Config:
    """BM25 full-text search configuration."""

    enabled: bool = True
    language: Literal["zh", "en"] = "zh"


@dataclass
class LLMConfig:
    """LLM configuration for extraction / scenes / persona."""

    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    max_tokens: int = 4096
    timeout_ms: int = 120_000


@dataclass
class OffloadConfig:
    """Context offload and compression configuration."""

    enabled: bool = False


@dataclass
class MemoryConfig:
    """Top-level configuration for the TDAI memory system."""

    # ── Storage ──
    postgres_url: str = "postgresql://localhost:5432/tdai_memory"
    postgres_schema: str = "public"
    qdrant_url: str = "http://localhost:6333"

    # ── Data directory (file-based assets: persona.md, scenes, etc.) ──
    data_dir: str = "./tdai_data"

    # ── Embedding ──
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)

    # ── Subsystem configs ──
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    recall: RecallConfig = field(default_factory=RecallConfig)
    bm25: BM25Config = field(default_factory=BM25Config)
    llm: LLMConfig = field(default_factory=LLMConfig)
    offload: OffloadConfig = field(default_factory=OffloadConfig)

    # ── Convenience shortcuts (set these and they propagate to sub-configs) ──

    @property
    def embedding_api_key(self) -> str:
        return self.embedding.api_key

    @embedding_api_key.setter
    def embedding_api_key(self, value: str) -> None:
        self.embedding.api_key = value

    @property
    def embedding_model(self) -> str:
        return self.embedding.model

    @embedding_model.setter
    def embedding_model(self, value: str) -> None:
        self.embedding.model = value

    @property
    def embedding_base_url(self) -> str:
        return self.embedding.base_url

    @embedding_base_url.setter
    def embedding_base_url(self, value: str) -> None:
        self.embedding.base_url = value

    @property
    def llm_model(self) -> str:
        return self.llm.model

    @llm_model.setter
    def llm_model(self, value: str) -> None:
        self.llm.model = value

    @property
    def llm_api_key(self) -> str:
        return self.llm.api_key

    @llm_api_key.setter
    def llm_api_key(self, value: str) -> None:
        self.llm.api_key = value

    @property
    def llm_base_url(self) -> str:
        return self.llm.base_url

    @llm_base_url.setter
    def llm_base_url(self, value: str) -> None:
        self.llm.base_url = value

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """Build a MemoryConfig from agent-server environment variables."""
        from urllib.parse import quote_plus

        pg_host = os.getenv("POSTGRES_HOST", "localhost")
        pg_port = os.getenv("POSTGRES_PORT", "5432")
        pg_user = os.getenv("POSTGRES_USER", "postgres")
        pg_password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
        pg_db = os.getenv("POSTGRES_DB", "postgres")
        postgres_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"

        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = os.getenv("QDRANT_PORT", "6333")

        embedding_dim = int(os.getenv("EMBEDDING_DIMENSION", "0") or "0")

        return cls(
            postgres_url=postgres_url,
            postgres_schema=os.getenv("MEMORY_SCHEMA", "memories"),
            qdrant_url=f"http://{qdrant_host}:{qdrant_port}",
            data_dir=os.getenv("MEMORY_DATA_DIR", "./tdai_data"),
            embedding=EmbeddingConfig(
                api_key=os.getenv("EMBEDDING_LLM_API_KEY", "NO_KEY"),
                base_url=os.getenv("EMBEDDING_LLM_ENDPOINT", "http://localhost:8605"),
                model=os.getenv("EMBEDDING_LLM_MODEL", "qwen3-embedding-4b"),
                dimensions=embedding_dim,
            ),
            llm=LLMConfig(
                api_key=os.getenv("TDAI_LLM_API_KEY", "NO_KEY"),
                base_url=os.getenv("TDAI_LLM_ENDPOINT", "http://localhost:8601/v1"),
                model=os.getenv("TDAI_LLM_MODEL", "qwen3.6-35b-a3b"),
            ),
        )
