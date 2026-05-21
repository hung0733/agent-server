import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from tdai_memory.store import qdrant as qdrant_module
from tdai_memory.store.qdrant import QdrantStore


class FakeQdrantClient:
    def __init__(self) -> None:
        self.created_collections = []
        self.indexed_collections = []

    async def get_collections(self):
        return SimpleNamespace(collections=[])

    async def create_collection(self, *, collection_name, vectors_config):
        self.created_collections.append(collection_name)

    async def create_payload_index(self, *, collection_name, field_name, field_schema):
        self.indexed_collections.append(collection_name)


@pytest.mark.asyncio
async def test_qdrant_store_uses_configured_collection_names(monkeypatch):
    client = FakeQdrantClient()
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", lambda url: client)
    store = QdrantStore(
        "http://qdrant.example:6333",
        2560,
        l0_collection="agent_l0",
        l1_collection="agent_l1",
    )

    await store.initialize()

    assert client.created_collections == ["agent_l0", "agent_l1"]
    assert client.indexed_collections == ["agent_l0", "agent_l1"]
