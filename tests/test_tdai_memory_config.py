import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from tdai_memory.config import MemoryConfig, resolve_openai_api_key
from tdai_memory.manager import MemoryManager


LEGACY_ENV_NAMES = (
    "MEMORY_SCHEMA",
    "MEMORY_DATA_DIR",
    "TDAI_LLM_ENDPOINT",
    "TDAI_LLM_API_KEY",
    "TDAI_LLM_MODEL",
    "MEMORY_OFFLOAD_ENABLED",
)


def clear_memory_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("TDAI_MEM_"):
            monkeypatch.delenv(name, raising=False)

    for name in LEGACY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_from_env_returns_defaults_without_tdai_mem_env(monkeypatch):
    clear_memory_env(monkeypatch)

    assert MemoryManager.from_env() == MemoryConfig()


def test_from_env_reads_tdai_mem_values(monkeypatch):
    clear_memory_env(monkeypatch)
    monkeypatch.setenv("TDAI_MEM_POSTGRES_URL", "postgresql://db.example/memory")
    monkeypatch.setenv("TDAI_MEM_POSTGRES_SCHEMA", "memory_schema")
    monkeypatch.setenv("TDAI_MEM_QDRANT_URL", "http://qdrant.example:6333")
    monkeypatch.setenv("TDAI_MEM_QDRANT_L0_COLLECTION", "custom_l0")
    monkeypatch.setenv("TDAI_MEM_QDRANT_L1_COLLECTION", "custom_l1")
    monkeypatch.setenv("TDAI_MEM_DATA_DIR", "/var/lib/tdai_memory")
    monkeypatch.setenv("TDAI_MEM_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("TDAI_MEM_EMBEDDING_BASE_URL", "http://embedding.example")
    monkeypatch.setenv("TDAI_MEM_EMBEDDING_DIMENSIONS", "1536")
    monkeypatch.setenv("TDAI_MEM_CAPTURE_ENABLED", "false")
    monkeypatch.setenv("TDAI_MEM_EXTRACTION_MODEL", "extract-model")
    monkeypatch.setenv("TDAI_MEM_PIPELINE_ENABLE_WARMUP", "0")
    monkeypatch.setenv("TDAI_MEM_RECALL_SCORE_THRESHOLD", "0.42")
    monkeypatch.setenv("TDAI_MEM_RECALL_STRATEGY", "keyword")
    monkeypatch.setenv("TDAI_MEM_BM25_LANGUAGE", "en")
    monkeypatch.setenv("TDAI_MEM_LLM_ENABLED", "true")
    monkeypatch.setenv("TDAI_MEM_LLM_BASE_URL", "http://llm.example")
    monkeypatch.setenv("TDAI_MEM_LLM_MAX_TOKENS", "2048")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_ENABLED", "yes")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_TEMPERATURE", "0.7")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_BACKEND_URL", "http://offload.example")

    config = MemoryManager.from_env()

    assert config.postgres_url == "postgresql://db.example/memory"
    assert config.postgres_schema == "memory_schema"
    assert config.qdrant_url == "http://qdrant.example:6333"
    assert config.qdrant_l0_collection == "custom_l0"
    assert config.qdrant_l1_collection == "custom_l1"
    assert config.data_dir == "/var/lib/tdai_memory"
    assert config.embedding.api_key == "embedding-key"
    assert config.embedding.base_url == "http://embedding.example/v1"
    assert config.embedding.dimensions == 1536
    assert config.capture.enabled is False
    assert config.extraction.model == "extract-model"
    assert config.pipeline.enable_warmup is False
    assert config.recall.score_threshold == 0.42
    assert config.recall.strategy == "keyword"
    assert config.bm25.language == "en"
    assert config.llm.enabled is True
    assert config.llm.base_url == "http://llm.example/v1"
    assert config.llm.max_tokens == 2048
    assert config.offload.enabled is True
    assert config.offload.temperature == 0.7
    assert config.offload.backend_url == "http://offload.example"


def test_from_env_empty_optional_strings_become_none(monkeypatch):
    clear_memory_env(monkeypatch)
    monkeypatch.setenv("TDAI_MEM_EXTRACTION_MODEL", "")
    monkeypatch.setenv("TDAI_MEM_PERSONA_MODEL", "")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_MODEL", "")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_DATA_DIR", "")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_BACKEND_URL", "")
    monkeypatch.setenv("TDAI_MEM_OFFLOAD_USER_ID", "")

    config = MemoryManager.from_env()

    assert config.extraction.model is None
    assert config.persona.model is None
    assert config.offload.model is None
    assert config.offload.data_dir is None
    assert config.offload.backend_url is None
    assert config.offload.user_id is None


def test_from_env_ignores_legacy_memory_env_names(monkeypatch):
    clear_memory_env(monkeypatch)
    monkeypatch.setenv("MEMORY_SCHEMA", "legacy_schema")
    monkeypatch.setenv("MEMORY_DATA_DIR", "/legacy/memory")
    monkeypatch.setenv("TDAI_LLM_ENDPOINT", "http://legacy-llm.example")
    monkeypatch.setenv("TDAI_LLM_API_KEY", "legacy-key")
    monkeypatch.setenv("TDAI_LLM_MODEL", "legacy-model")
    monkeypatch.setenv("MEMORY_OFFLOAD_ENABLED", "true")

    config = MemoryManager.from_env()

    assert config.postgres_schema == "public"
    assert config.data_dir == "./tdai_data"
    assert config.llm.base_url == "https://api.openai.com/v1"
    assert config.llm.api_key == ""
    assert config.llm.model == "gpt-4o"
    assert config.offload.enabled is False


def test_resolve_openai_api_key_allows_empty_key_for_custom_base_url():
    assert resolve_openai_api_key("", "http://llm.example/v1") == "not-required"
    assert resolve_openai_api_key("real-key", "http://llm.example/v1") == "real-key"
    assert resolve_openai_api_key("", "https://api.openai.com/v1") == ""
