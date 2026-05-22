"""Configuration for the TDAI memory system."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from backend.i18n import t
logger = logging.getLogger(__name__)


@dataclass
class CaptureConfig:
    """Auto-capture configuration."""

    enabled: bool = True
    l0_l1_retention_days: int = 0  # TTL in days, 0=disabled
    allow_aggressive_cleanup: bool = False


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
    dimensions: int = 0
    max_input_chars: int = 5000
    timeout_ms: int = 10000
    conflict_recall_top_k: int = 5
    recall_timeout_ms: int = 0
    capture_timeout_ms: int = 0


@dataclass
class BM25Config:
    """BM25 full-text search configuration."""

    enabled: bool = True
    language: Literal["zh", "en"] = "zh"


@dataclass
class LLMConfig:
    """LLM configuration for extraction / scenes / persona."""

    enabled: bool = False
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    max_tokens: int = 4096
    timeout_ms: int = 120_000


@dataclass
class OffloadConfig:
    """Context offload and compression configuration."""

    enabled: bool = False
    mode: str = "local"
    model: str | None = None
    temperature: float = 0.2
    force_trigger_threshold: int = 4
    data_dir: str | None = None
    default_context_window: int = 200000
    max_pairs_per_batch: int = 20
    l2_null_threshold: int = 4
    l2_timeout_seconds: int = 300
    mild_offload_ratio: float = 0.5
    aggressive_compress_ratio: float = 0.85
    mmd_max_token_ratio: float = 0.2
    offload_retention_days: int = 0
    backend_url: str | None = None
    backend_api_key: str = ""
    backend_timeout_ms: int = 120000
    log_max_size_mb: int = 50
    user_id: str | None = None
    mild_offload_scan_ratio: float = 0.7
    aggressive_delete_ratio: float = 0.4
    emergency_compress_ratio: float = 0.95
    emergency_target_ratio: float = 0.6


@dataclass
class MemoryConfig:
    """Top-level configuration for the TDAI memory system."""

    # ── Storage ──
    postgres_url: str = "postgresql://localhost:5432/tdai_memory"
    postgres_schema: str = "public"
    qdrant_url: str = "http://localhost:6333"
    qdrant_l0_collection: str = "l0_conversations"
    qdrant_l1_collection: str = "l1_memories"

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


def validate_config(config: MemoryConfig) -> str | None:
    if config.recall.strategy not in ("embedding", "keyword", "hybrid"):
        return "Invalid recall strategy: must be one of embedding, keyword, hybrid"

    if config.capture.l0_l1_retention_days in (1, 2) and not config.capture.allow_aggressive_cleanup:
        return "Retention days must be >= 3 or 0 to disable, unless allow_aggressive_cleanup is True"

    if config.embedding.dimensions > 0 and config.embedding.api_key == "":
        return "Embedding API key required when dimensions configured"

    if config.offload.enabled and config.offload.mode == "backend" and not config.offload.backend_url:
        logger.warning(t("tdai_memory.config.offload_backend_url_missing"))

    return None


def normalize_config(config: MemoryConfig) -> MemoryConfig:
    if config.embedding.base_url and not config.embedding.base_url.endswith("/v1"):
        if not config.embedding.base_url.endswith("/"):
            config.embedding.base_url += "/v1"

    if config.llm.base_url and not config.llm.base_url.endswith("/v1"):
        if not config.llm.base_url.endswith("/"):
            config.llm.base_url += "/v1"

    if config.recall.timeout_ms <= 0:
        config.recall.timeout_ms = 5000

    if config.pipeline.l1_idle_timeout_seconds <= 0:
        config.pipeline.l1_idle_timeout_seconds = 600

    if 0 < config.offload.offload_retention_days < 3:
        config.offload.offload_retention_days = 0

    if config.llm.timeout_ms <= 0:
        config.llm.timeout_ms = 120_000

    if config.embedding.timeout_ms <= 0:
        config.embedding.timeout_ms = 10000

    return config


def resolve_openai_api_key(api_key: str, base_url: str) -> str:
    if api_key:
        return api_key
    if base_url and "api.openai.com" not in base_url:
        return "not-required"
    return api_key
