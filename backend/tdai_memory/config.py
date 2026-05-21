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
    jsonl_filename: str = "offload.jsonl"
    refs_dir: str = "refs"
    mmds_dir: str = "mmds"
    default_compression_level: Literal["mild", "aggressive", "emergency"] = "mild"
    mild_recent_entries: int = 10
    mild_inline_score_threshold: int = 3
    aggressive_recent_entries: int = 15
    emergency_recent_entries: int = 20
    summarizer_max_result_chars: int = 4000
    mermaid_entry_summary_chars: int = 200
    tool_call_label_chars: int = 80


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

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """Build a MemoryConfig from agent-server environment variables."""
        from urllib.parse import quote_plus

        defaults = cls()

        def env_str(name: str, default: str | None) -> str | None:
            value = os.getenv(name)
            if value is None or value == "":
                return default
            return value

        def env_bool(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None or value == "":
                return default
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}

        def env_int(name: str, default: int) -> int:
            value = os.getenv(name)
            if value is None or value == "":
                return default
            return int(value)

        def env_float(name: str, default: float) -> float:
            value = os.getenv(name)
            if value is None or value == "":
                return default
            return float(value)

        pg_host = os.getenv("POSTGRES_HOST", "localhost")
        pg_port = os.getenv("POSTGRES_PORT", "5432")
        pg_user = os.getenv("POSTGRES_USER", "postgres")
        pg_password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
        pg_db = os.getenv("POSTGRES_DB", "postgres")
        postgres_url = env_str(
            "MEMORY_POSTGRES_URL",
            f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}",
        )

        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = os.getenv("QDRANT_PORT", "6333")
        qdrant_url = env_str("MEMORY_QDRANT_URL", f"http://{qdrant_host}:{qdrant_port}")

        recall_strategy = env_str("MEMORY_RECALL_STRATEGY", defaults.recall.strategy)
        if recall_strategy not in {"embedding", "keyword", "hybrid"}:
            recall_strategy = defaults.recall.strategy

        bm25_language = env_str("MEMORY_BM25_LANGUAGE", defaults.bm25.language)
        if bm25_language not in {"zh", "en"}:
            bm25_language = defaults.bm25.language

        default_compression_level = env_str(
            "MEMORY_OFFLOAD_DEFAULT_COMPRESSION_LEVEL",
            defaults.offload.default_compression_level,
        )
        if default_compression_level not in {"mild", "aggressive", "emergency"}:
            default_compression_level = defaults.offload.default_compression_level

        return cls(
            postgres_url=postgres_url or defaults.postgres_url,
            postgres_schema=env_str("MEMORY_SCHEMA", "memories") or "memories",
            qdrant_url=qdrant_url or defaults.qdrant_url,
            qdrant_l0_collection=env_str(
                "QDRANT_L0_COLLECTION", defaults.qdrant_l0_collection
            ) or defaults.qdrant_l0_collection,
            qdrant_l1_collection=env_str(
                "QDRANT_L1_COLLECTION", defaults.qdrant_l1_collection
            ) or defaults.qdrant_l1_collection,
            data_dir=env_str("MEMORY_DATA_DIR", defaults.data_dir) or defaults.data_dir,
            embedding=EmbeddingConfig(
                api_key=env_str("EMBEDDING_LLM_API_KEY", defaults.embedding.api_key)
                or defaults.embedding.api_key,
                base_url=env_str("EMBEDDING_LLM_ENDPOINT", defaults.embedding.base_url)
                or defaults.embedding.base_url,
                model=env_str("EMBEDDING_LLM_MODEL", defaults.embedding.model)
                or defaults.embedding.model,
                dimensions=env_int("EMBEDDING_DIMENSION", defaults.embedding.dimensions),
                max_input_chars=env_int(
                    "MEMORY_EMBEDDING_MAX_INPUT_CHARS",
                    defaults.embedding.max_input_chars,
                ),
                timeout_ms=env_int(
                    "MEMORY_EMBEDDING_TIMEOUT_MS", defaults.embedding.timeout_ms
                ),
            ),
            capture=CaptureConfig(
                enabled=env_bool("MEMORY_CAPTURE_ENABLED", defaults.capture.enabled),
                l0_l1_retention_days=env_int(
                    "MEMORY_CAPTURE_L0_L1_RETENTION_DAYS",
                    defaults.capture.l0_l1_retention_days,
                ),
            ),
            extraction=ExtractionConfig(
                enabled=env_bool(
                    "MEMORY_EXTRACTION_ENABLED", defaults.extraction.enabled
                ),
                enable_dedup=env_bool(
                    "MEMORY_EXTRACTION_ENABLE_DEDUP",
                    defaults.extraction.enable_dedup,
                ),
                max_memories_per_session=env_int(
                    "MEMORY_EXTRACTION_MAX_MEMORIES_PER_SESSION",
                    defaults.extraction.max_memories_per_session,
                ),
                model=env_str("MEMORY_EXTRACTION_MODEL", defaults.extraction.model),
            ),
            persona=PersonaConfig(
                trigger_every_n=env_int(
                    "MEMORY_PERSONA_TRIGGER_EVERY_N",
                    defaults.persona.trigger_every_n,
                ),
                max_scenes=env_int("MEMORY_PERSONA_MAX_SCENES", defaults.persona.max_scenes),
                backup_count=env_int(
                    "MEMORY_PERSONA_BACKUP_COUNT", defaults.persona.backup_count
                ),
                scene_backup_count=env_int(
                    "MEMORY_PERSONA_SCENE_BACKUP_COUNT",
                    defaults.persona.scene_backup_count,
                ),
                model=env_str("MEMORY_PERSONA_MODEL", defaults.persona.model),
            ),
            pipeline=PipelineConfig(
                every_n_conversations=env_int(
                    "MEMORY_PIPELINE_EVERY_N_CONVERSATIONS",
                    defaults.pipeline.every_n_conversations,
                ),
                enable_warmup=env_bool(
                    "MEMORY_PIPELINE_ENABLE_WARMUP",
                    defaults.pipeline.enable_warmup,
                ),
                l1_idle_timeout_seconds=env_int(
                    "MEMORY_PIPELINE_L1_IDLE_TIMEOUT_SECONDS",
                    defaults.pipeline.l1_idle_timeout_seconds,
                ),
                l2_delay_after_l1_seconds=env_int(
                    "MEMORY_PIPELINE_L2_DELAY_AFTER_L1_SECONDS",
                    defaults.pipeline.l2_delay_after_l1_seconds,
                ),
                l2_min_interval_seconds=env_int(
                    "MEMORY_PIPELINE_L2_MIN_INTERVAL_SECONDS",
                    defaults.pipeline.l2_min_interval_seconds,
                ),
                l2_max_interval_seconds=env_int(
                    "MEMORY_PIPELINE_L2_MAX_INTERVAL_SECONDS",
                    defaults.pipeline.l2_max_interval_seconds,
                ),
                session_active_window_hours=env_int(
                    "MEMORY_PIPELINE_SESSION_ACTIVE_WINDOW_HOURS",
                    defaults.pipeline.session_active_window_hours,
                ),
            ),
            recall=RecallConfig(
                enabled=env_bool("MEMORY_RECALL_ENABLED", defaults.recall.enabled),
                max_results=env_int("MEMORY_RECALL_MAX_RESULTS", defaults.recall.max_results),
                score_threshold=env_float(
                    "MEMORY_RECALL_SCORE_THRESHOLD", defaults.recall.score_threshold
                ),
                strategy=recall_strategy,  # type: ignore[arg-type]
                timeout_ms=env_int("MEMORY_RECALL_TIMEOUT_MS", defaults.recall.timeout_ms),
            ),
            bm25=BM25Config(
                enabled=env_bool("MEMORY_BM25_ENABLED", defaults.bm25.enabled),
                language=bm25_language,  # type: ignore[arg-type]
            ),
            llm=LLMConfig(
                api_key=env_str("TDAI_LLM_API_KEY", defaults.llm.api_key)
                or defaults.llm.api_key,
                base_url=env_str("TDAI_LLM_ENDPOINT", defaults.llm.base_url)
                or defaults.llm.base_url,
                model=env_str("TDAI_LLM_MODEL", defaults.llm.model)
                or defaults.llm.model,
                max_tokens=env_int("MEMORY_LLM_MAX_TOKENS", defaults.llm.max_tokens),
                timeout_ms=env_int("MEMORY_LLM_TIMEOUT_MS", defaults.llm.timeout_ms),
            ),
            offload=OffloadConfig(
                enabled=env_bool("MEMORY_OFFLOAD_ENABLED", defaults.offload.enabled),
                jsonl_filename=env_str(
                    "MEMORY_OFFLOAD_JSONL_FILENAME", defaults.offload.jsonl_filename
                )
                or defaults.offload.jsonl_filename,
                refs_dir=env_str("MEMORY_OFFLOAD_REFS_DIR", defaults.offload.refs_dir)
                or defaults.offload.refs_dir,
                mmds_dir=env_str("MEMORY_OFFLOAD_MMDS_DIR", defaults.offload.mmds_dir)
                or defaults.offload.mmds_dir,
                default_compression_level=default_compression_level,  # type: ignore[arg-type]
                mild_recent_entries=env_int(
                    "MEMORY_OFFLOAD_MILD_RECENT_ENTRIES",
                    defaults.offload.mild_recent_entries,
                ),
                mild_inline_score_threshold=env_int(
                    "MEMORY_OFFLOAD_MILD_INLINE_SCORE_THRESHOLD",
                    defaults.offload.mild_inline_score_threshold,
                ),
                aggressive_recent_entries=env_int(
                    "MEMORY_OFFLOAD_AGGRESSIVE_RECENT_ENTRIES",
                    defaults.offload.aggressive_recent_entries,
                ),
                emergency_recent_entries=env_int(
                    "MEMORY_OFFLOAD_EMERGENCY_RECENT_ENTRIES",
                    defaults.offload.emergency_recent_entries,
                ),
                summarizer_max_result_chars=env_int(
                    "MEMORY_OFFLOAD_SUMMARIZER_MAX_RESULT_CHARS",
                    defaults.offload.summarizer_max_result_chars,
                ),
                mermaid_entry_summary_chars=env_int(
                    "MEMORY_OFFLOAD_MERMAID_ENTRY_SUMMARY_CHARS",
                    defaults.offload.mermaid_entry_summary_chars,
                ),
                tool_call_label_chars=env_int(
                    "MEMORY_OFFLOAD_TOOL_CALL_LABEL_CHARS",
                    defaults.offload.tool_call_label_chars,
                ),
            ),
        )
