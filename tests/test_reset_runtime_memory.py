from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import reset_runtime_memory as reset_script


def _clear_reset_env(monkeypatch):
    for name in list(
        {
            "DATABASE_URL",
            "LANGGRAPH_SCHEMA",
            "POSTGRES_DB",
            "POSTGRES_HOST",
            "POSTGRES_PASSWORD",
            "POSTGRES_PORT",
            "POSTGRES_USER",
            "TDAI_MEM_DATA_DIR",
            "TDAI_MEM_EMBEDDING_DIMENSIONS",
            "TDAI_MEM_POSTGRES_SCHEMA",
            "TDAI_MEM_POSTGRES_URL",
            "TDAI_MEM_QDRANT_L0_COLLECTION",
            "TDAI_MEM_QDRANT_L1_COLLECTION",
            "TDAI_MEM_QDRANT_URL",
        }
    ):
        monkeypatch.delenv(name, raising=False)


def test_memory_file_cleanup_preserves_soul_and_identity(tmp_path):
    data_dir = tmp_path / "memory"
    agent_dir = data_dir / "agent-1"
    conversations_dir = agent_dir / "conversations"
    scene_dir = agent_dir / "scene_blocks"
    conversations_dir.mkdir(parents=True)
    scene_dir.mkdir()
    (agent_dir / "SOUL.md").write_text("soul", encoding="utf-8")
    (agent_dir / "IDENTITY.md").write_text("identity", encoding="utf-8")
    (agent_dir / "persona.md").write_text("persona", encoding="utf-8")
    (conversations_dir / "2026-05-22.jsonl").write_text("{}", encoding="utf-8")
    (scene_dir / "scene.md").write_text("scene", encoding="utf-8")

    dry_targets = reset_script.reset_memory_files(str(data_dir), dry_run=True)

    assert {path.name for path in dry_targets} == {
        "conversations",
        "persona.md",
        "scene_blocks",
    }
    assert (agent_dir / "persona.md").exists()
    assert conversations_dir.exists()

    reset_script.reset_memory_files(str(data_dir), dry_run=False)

    assert (agent_dir / "SOUL.md").read_text(encoding="utf-8") == "soul"
    assert (agent_dir / "IDENTITY.md").read_text(encoding="utf-8") == "identity"
    assert not (agent_dir / "persona.md").exists()
    assert not conversations_dir.exists()
    assert not scene_dir.exists()
    assert data_dir.exists()


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePostgresConn:
    def __init__(self):
        self.executed = []
        self.closed = False

    async def fetch(self, query, schema):
        if schema == "memories":
            return [{"table_name": "l0_conversations"}, {"table_name": "l1_records"}]
        if schema == "langgraph":
            return [{"table_name": "checkpoints"}, {"table_name": "writes"}]
        return []

    async def fetchval(self, query):
        counts = {
            'SELECT COUNT(*) FROM "memories"."l0_conversations"': 11,
            'SELECT COUNT(*) FROM "memories"."l1_records"': 22,
            'SELECT COUNT(*) FROM "langgraph"."checkpoints"': 33,
            'SELECT COUNT(*) FROM "langgraph"."writes"': 44,
            'SELECT COUNT(*) FROM "public"."agent_msg_hist"': 7,
            (
                'SELECT COUNT(*) FROM "public"."session"'
                " WHERE session_id NOT LIKE 'default-%'"
            ): 3,
        }
        return counts[query]

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if query.startswith("DELETE FROM public.agent_msg_hist"):
            return "DELETE 7"
        if query.startswith("DELETE FROM public.session"):
            return "DELETE 3"
        return "TRUNCATE TABLE"

    def transaction(self):
        return FakeTransaction()

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_postgres_dry_run_discovers_tables_without_deleting(monkeypatch):
    _clear_reset_env(monkeypatch)
    conn = FakePostgresConn()
    monkeypatch.setenv("TDAI_MEM_POSTGRES_URL", "postgresql://db/memory")
    monkeypatch.setenv("TDAI_MEM_POSTGRES_SCHEMA", "memories")
    monkeypatch.setenv("LANGGRAPH_SCHEMA", "langgraph")

    async def fake_connect(url):
        return conn

    monkeypatch.setattr(reset_script.asyncpg, "connect", fake_connect)

    summary = await reset_script.reset_postgres(dry_run=True)

    assert summary["memory_tables"] == ["l0_conversations", "l1_records"]
    assert summary["memory_table_counts"] == {
        "l0_conversations": 11,
        "l1_records": 22,
    }
    assert summary["langgraph_tables"] == ["checkpoints", "writes"]
    assert summary["langgraph_table_counts"] == {
        "checkpoints": 33,
        "writes": 44,
    }
    assert summary["agent_msg_hist_count"] == 7
    assert summary["non_default_session_count"] == 3
    assert conn.executed == []
    assert conn.closed is True


@pytest.mark.asyncio
async def test_postgres_apply_clears_runtime_tables(monkeypatch):
    _clear_reset_env(monkeypatch)
    conn = FakePostgresConn()
    monkeypatch.setenv("TDAI_MEM_POSTGRES_URL", "postgresql://db/memory")
    monkeypatch.setenv("TDAI_MEM_POSTGRES_SCHEMA", "memories")
    monkeypatch.setenv("LANGGRAPH_SCHEMA", "langgraph")

    async def fake_connect(url):
        return conn

    monkeypatch.setattr(reset_script.asyncpg, "connect", fake_connect)

    summary = await reset_script.reset_postgres(dry_run=False)
    statements = [query for query, _ in conn.executed]

    assert any('"memories"."l0_conversations"' in query for query in statements)
    assert any('"langgraph"."checkpoints"' in query for query in statements)
    assert "DELETE FROM public.agent_msg_hist" in statements
    assert "DELETE FROM public.session WHERE session_id NOT LIKE 'default-%'" in statements
    assert summary["memory_table_counts"]["l0_conversations"] == 11
    assert summary["langgraph_table_counts"]["checkpoints"] == 33
    assert summary["agent_msg_hist_count"] == 7
    assert summary["non_default_session_count"] == 3
    assert summary["agent_msg_hist_deleted"] == 7
    assert summary["sessions_deleted"] == 3
    assert conn.closed is True


class FakeQdrantClient:
    def __init__(self):
        self.deleted = []
        self.created = []
        self.indexed = []
        self.closed = False

    async def get_collections(self):
        return SimpleNamespace(
            collections=[
                SimpleNamespace(name="agent_l0"),
                SimpleNamespace(name="unrelated"),
            ]
        )

    async def delete_collection(self, *, collection_name):
        self.deleted.append(collection_name)

    async def create_collection(self, *, collection_name, vectors_config):
        self.created.append((collection_name, vectors_config.size))

    async def create_payload_index(self, *, collection_name, field_name, field_schema):
        self.indexed.append((collection_name, field_name, field_schema))

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_qdrant_dry_run_does_not_mutate(monkeypatch):
    _clear_reset_env(monkeypatch)
    client = FakeQdrantClient()
    monkeypatch.setenv("TDAI_MEM_QDRANT_URL", "http://qdrant.example:6333")
    monkeypatch.setenv("TDAI_MEM_QDRANT_L0_COLLECTION", "agent_l0")
    monkeypatch.setenv("TDAI_MEM_QDRANT_L1_COLLECTION", "agent_l1")
    monkeypatch.setattr(reset_script, "AsyncQdrantClient", lambda url: client)

    summary = await reset_script.reset_qdrant(dry_run=True)

    assert summary["existing"] == ["agent_l0"]
    assert summary["missing"] == ["agent_l1"]
    assert client.deleted == []
    assert client.created == []
    assert client.closed is True


@pytest.mark.asyncio
async def test_qdrant_apply_only_recreates_configured_memory_collections(monkeypatch):
    _clear_reset_env(monkeypatch)
    client = FakeQdrantClient()
    monkeypatch.setenv("TDAI_MEM_QDRANT_URL", "http://qdrant.example:6333")
    monkeypatch.setenv("TDAI_MEM_QDRANT_L0_COLLECTION", "agent_l0")
    monkeypatch.setenv("TDAI_MEM_QDRANT_L1_COLLECTION", "agent_l1")
    monkeypatch.setenv("TDAI_MEM_EMBEDDING_DIMENSIONS", "2560")
    monkeypatch.setattr(reset_script, "AsyncQdrantClient", lambda url: client)

    await reset_script.reset_qdrant(dry_run=False)

    assert client.deleted == ["agent_l0"]
    assert client.created == [("agent_l0", 2560), ("agent_l1", 2560)]
    assert [item[0] for item in client.indexed] == ["agent_l0", "agent_l1"]
    assert "unrelated" not in client.deleted
    assert client.closed is True
