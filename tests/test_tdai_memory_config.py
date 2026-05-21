import ast
from pathlib import Path

from backend.tdai_memory.config import MemoryConfig


def test_memory_config_from_env_reads_all_overrides(monkeypatch):
    values = {
        "POSTGRES_HOST": "db-host",
        "POSTGRES_PORT": "15432",
        "POSTGRES_USER": "memory_user",
        "POSTGRES_PASSWORD": "p@ss word",
        "POSTGRES_DB": "memory_db",
        "MEMORY_POSTGRES_URL": "postgresql://direct:direct@direct-host:5432/direct_db",
        "MEMORY_SCHEMA": "memory_schema",
        "QDRANT_HOST": "qdrant-host",
        "QDRANT_PORT": "16333",
        "MEMORY_QDRANT_URL": "http://direct-qdrant:6333",
        "QDRANT_L0_COLLECTION": "custom_l0",
        "QDRANT_L1_COLLECTION": "custom_l1",
        "MEMORY_DATA_DIR": "/tmp/memory",
        "EMBEDDING_LLM_API_KEY": "embedding-key",
        "EMBEDDING_LLM_ENDPOINT": "http://embedding/v1",
        "EMBEDDING_LLM_MODEL": "embedding-model",
        "EMBEDDING_DIMENSION": "42",
        "MEMORY_EMBEDDING_MAX_INPUT_CHARS": "1234",
        "MEMORY_EMBEDDING_TIMEOUT_MS": "4321",
        "MEMORY_CAPTURE_ENABLED": "false",
        "MEMORY_CAPTURE_L0_L1_RETENTION_DAYS": "7",
        "MEMORY_EXTRACTION_ENABLED": "false",
        "MEMORY_EXTRACTION_ENABLE_DEDUP": "false",
        "MEMORY_EXTRACTION_MAX_MEMORIES_PER_SESSION": "11",
        "MEMORY_EXTRACTION_MODEL": "extract-model",
        "MEMORY_PERSONA_TRIGGER_EVERY_N": "12",
        "MEMORY_PERSONA_MAX_SCENES": "13",
        "MEMORY_PERSONA_BACKUP_COUNT": "14",
        "MEMORY_PERSONA_SCENE_BACKUP_COUNT": "15",
        "MEMORY_PERSONA_MODEL": "persona-model",
        "MEMORY_PIPELINE_EVERY_N_CONVERSATIONS": "16",
        "MEMORY_PIPELINE_ENABLE_WARMUP": "false",
        "MEMORY_PIPELINE_L1_IDLE_TIMEOUT_SECONDS": "17",
        "MEMORY_PIPELINE_L2_DELAY_AFTER_L1_SECONDS": "18",
        "MEMORY_PIPELINE_L2_MIN_INTERVAL_SECONDS": "19",
        "MEMORY_PIPELINE_L2_MAX_INTERVAL_SECONDS": "20",
        "MEMORY_PIPELINE_SESSION_ACTIVE_WINDOW_HOURS": "21",
        "MEMORY_RECALL_ENABLED": "false",
        "MEMORY_RECALL_MAX_RESULTS": "22",
        "MEMORY_RECALL_SCORE_THRESHOLD": "0.77",
        "MEMORY_RECALL_STRATEGY": "keyword",
        "MEMORY_RECALL_TIMEOUT_MS": "23",
        "MEMORY_BM25_ENABLED": "false",
        "MEMORY_BM25_LANGUAGE": "en",
        "TDAI_LLM_API_KEY": "tdai-key",
        "TDAI_LLM_ENDPOINT": "http://tdai/v1",
        "TDAI_LLM_MODEL": "tdai-model",
        "MEMORY_LLM_MAX_TOKENS": "2048",
        "MEMORY_LLM_TIMEOUT_MS": "240000",
        "MEMORY_OFFLOAD_ENABLED": "true",
        "MEMORY_OFFLOAD_JSONL_FILENAME": "custom-offload.jsonl",
        "MEMORY_OFFLOAD_REFS_DIR": "custom-refs",
        "MEMORY_OFFLOAD_MMDS_DIR": "custom-mmds",
        "MEMORY_OFFLOAD_DEFAULT_COMPRESSION_LEVEL": "aggressive",
        "MEMORY_OFFLOAD_MILD_RECENT_ENTRIES": "31",
        "MEMORY_OFFLOAD_MILD_INLINE_SCORE_THRESHOLD": "2",
        "MEMORY_OFFLOAD_AGGRESSIVE_RECENT_ENTRIES": "32",
        "MEMORY_OFFLOAD_EMERGENCY_RECENT_ENTRIES": "33",
        "MEMORY_OFFLOAD_SUMMARIZER_MAX_RESULT_CHARS": "12345",
        "MEMORY_OFFLOAD_MERMAID_ENTRY_SUMMARY_CHARS": "234",
        "MEMORY_OFFLOAD_TOOL_CALL_LABEL_CHARS": "91",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    config = MemoryConfig.from_env()

    assert config.postgres_url == "postgresql://direct:direct@direct-host:5432/direct_db"
    assert config.postgres_schema == "memory_schema"
    assert config.qdrant_url == "http://direct-qdrant:6333"
    assert config.qdrant_l0_collection == "custom_l0"
    assert config.qdrant_l1_collection == "custom_l1"
    assert config.data_dir == "/tmp/memory"
    assert config.embedding.api_key == "embedding-key"
    assert config.embedding.base_url == "http://embedding/v1"
    assert config.embedding.model == "embedding-model"
    assert config.embedding.dimensions == 42
    assert config.embedding.max_input_chars == 1234
    assert config.embedding.timeout_ms == 4321
    assert config.capture.enabled is False
    assert config.capture.l0_l1_retention_days == 7
    assert config.extraction.enabled is False
    assert config.extraction.enable_dedup is False
    assert config.extraction.max_memories_per_session == 11
    assert config.extraction.model == "extract-model"
    assert config.persona.trigger_every_n == 12
    assert config.persona.max_scenes == 13
    assert config.persona.backup_count == 14
    assert config.persona.scene_backup_count == 15
    assert config.persona.model == "persona-model"
    assert config.pipeline.every_n_conversations == 16
    assert config.pipeline.enable_warmup is False
    assert config.pipeline.l1_idle_timeout_seconds == 17
    assert config.pipeline.l2_delay_after_l1_seconds == 18
    assert config.pipeline.l2_min_interval_seconds == 19
    assert config.pipeline.l2_max_interval_seconds == 20
    assert config.pipeline.session_active_window_hours == 21
    assert config.recall.enabled is False
    assert config.recall.max_results == 22
    assert config.recall.score_threshold == 0.77
    assert config.recall.strategy == "keyword"
    assert config.recall.timeout_ms == 23
    assert config.bm25.enabled is False
    assert config.bm25.language == "en"
    assert config.llm.api_key == "tdai-key"
    assert config.llm.base_url == "http://tdai/v1"
    assert config.llm.model == "tdai-model"
    assert config.llm.max_tokens == 2048
    assert config.llm.timeout_ms == 240000
    assert config.offload.enabled is True
    assert config.offload.jsonl_filename == "custom-offload.jsonl"
    assert config.offload.refs_dir == "custom-refs"
    assert config.offload.mmds_dir == "custom-mmds"
    assert config.offload.default_compression_level == "aggressive"
    assert config.offload.mild_recent_entries == 31
    assert config.offload.mild_inline_score_threshold == 2
    assert config.offload.aggressive_recent_entries == 32
    assert config.offload.emergency_recent_entries == 33
    assert config.offload.summarizer_max_result_chars == 12345
    assert config.offload.mermaid_entry_summary_chars == 234
    assert config.offload.tool_call_label_chars == 91


def test_env_example_lists_all_memory_config_fields():
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    expected_env_names = [
        "MEMORY_POSTGRES_URL",
        "MEMORY_SCHEMA",
        "MEMORY_QDRANT_URL",
        "QDRANT_L0_COLLECTION",
        "QDRANT_L1_COLLECTION",
        "MEMORY_DATA_DIR",
        "EMBEDDING_LLM_API_KEY",
        "EMBEDDING_LLM_ENDPOINT",
        "EMBEDDING_LLM_MODEL",
        "EMBEDDING_DIMENSION",
        "MEMORY_EMBEDDING_MAX_INPUT_CHARS",
        "MEMORY_EMBEDDING_TIMEOUT_MS",
        "MEMORY_CAPTURE_ENABLED",
        "MEMORY_CAPTURE_L0_L1_RETENTION_DAYS",
        "MEMORY_EXTRACTION_ENABLED",
        "MEMORY_EXTRACTION_ENABLE_DEDUP",
        "MEMORY_EXTRACTION_MAX_MEMORIES_PER_SESSION",
        "MEMORY_EXTRACTION_MODEL",
        "MEMORY_PERSONA_TRIGGER_EVERY_N",
        "MEMORY_PERSONA_MAX_SCENES",
        "MEMORY_PERSONA_BACKUP_COUNT",
        "MEMORY_PERSONA_SCENE_BACKUP_COUNT",
        "MEMORY_PERSONA_MODEL",
        "MEMORY_PIPELINE_EVERY_N_CONVERSATIONS",
        "MEMORY_PIPELINE_ENABLE_WARMUP",
        "MEMORY_PIPELINE_L1_IDLE_TIMEOUT_SECONDS",
        "MEMORY_PIPELINE_L2_DELAY_AFTER_L1_SECONDS",
        "MEMORY_PIPELINE_L2_MIN_INTERVAL_SECONDS",
        "MEMORY_PIPELINE_L2_MAX_INTERVAL_SECONDS",
        "MEMORY_PIPELINE_SESSION_ACTIVE_WINDOW_HOURS",
        "MEMORY_RECALL_ENABLED",
        "MEMORY_RECALL_MAX_RESULTS",
        "MEMORY_RECALL_SCORE_THRESHOLD",
        "MEMORY_RECALL_STRATEGY",
        "MEMORY_RECALL_TIMEOUT_MS",
        "MEMORY_BM25_ENABLED",
        "MEMORY_BM25_LANGUAGE",
        "TDAI_LLM_API_KEY",
        "TDAI_LLM_ENDPOINT",
        "TDAI_LLM_MODEL",
        "MEMORY_LLM_MAX_TOKENS",
        "MEMORY_LLM_TIMEOUT_MS",
        "MEMORY_OFFLOAD_ENABLED",
        "MEMORY_OFFLOAD_JSONL_FILENAME",
        "MEMORY_OFFLOAD_REFS_DIR",
        "MEMORY_OFFLOAD_MMDS_DIR",
        "MEMORY_OFFLOAD_DEFAULT_COMPRESSION_LEVEL",
        "MEMORY_OFFLOAD_MILD_RECENT_ENTRIES",
        "MEMORY_OFFLOAD_MILD_INLINE_SCORE_THRESHOLD",
        "MEMORY_OFFLOAD_AGGRESSIVE_RECENT_ENTRIES",
        "MEMORY_OFFLOAD_EMERGENCY_RECENT_ENTRIES",
        "MEMORY_OFFLOAD_SUMMARIZER_MAX_RESULT_CHARS",
        "MEMORY_OFFLOAD_MERMAID_ENTRY_SUMMARY_CHARS",
        "MEMORY_OFFLOAD_TOOL_CALL_LABEL_CHARS",
    ]

    missing = [
        env_name
        for env_name in expected_env_names
        if f"\n{env_name}=" not in f"\n{env_example}"
    ]
    assert missing == []


def test_tdai_memory_logger_messages_use_i18n_keys():
    root = Path(__file__).resolve().parents[1] / "backend" / "tdai_memory"
    violations = []

    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in {"debug", "info", "warning", "error", "exception", "critical"}:
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "logger":
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                violations.append(f"{path.relative_to(root)}:{node.lineno}")

    assert violations == []
