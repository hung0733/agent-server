import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from tdai_memory.store import qdrant as qdrant_module
from tdai_memory.store.qdrant import QdrantStore
from tdai_memory.models import L0Record, MemoryRecord


class FakeQdrantClient:
    def __init__(self) -> None:
        self.created_collections = []
        self.indexed_collections = []
        self.upserts = []
        self.deletes = []
        self.query_points_calls = []
        self.query_points_response = SimpleNamespace(points=[])

    async def get_collections(self):
        return SimpleNamespace(collections=[])

    async def create_collection(self, *, collection_name, vectors_config):
        self.created_collections.append(collection_name)

    async def create_payload_index(self, *, collection_name, field_name, field_schema):
        self.indexed_collections.append(collection_name)

    async def upsert(self, *, collection_name, points):
        self.upserts.append((collection_name, points))

    async def delete(self, *, collection_name, points_selector):
        self.deletes.append((collection_name, points_selector))

    async def query_points(
        self,
        *,
        collection_name,
        query,
        limit,
        query_filter,
        with_payload,
    ):
        self.query_points_calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "limit": limit,
                "query_filter": query_filter,
                "with_payload": with_payload,
            }
        )
        return self.query_points_response


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


@pytest.mark.asyncio
async def test_qdrant_store_maps_l0_record_id_to_valid_point_id(monkeypatch):
    client = FakeQdrantClient()
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", lambda url: client)
    store = QdrantStore("http://qdrant.example:6333", 3)
    record = L0Record(
        id="l0_default-session_1779762096_0_e3a8",
        agent_id="agent-1",
        session_key="default-session",
        role="user",
        message_text="hi",
        recorded_at="2026-05-26T02:21:37+00:00",
        timestamp=1779762096,
    )

    await store.upsert_l0(record, [0.1, 0.2, 0.3])
    await store.delete_l0(record.id)

    point = client.upserts[0][1][0]
    uuid.UUID(str(point.id))
    assert point.id != record.id
    assert point.payload["id"] == record.id
    assert client.deletes[0][1].points == [point.id]


@pytest.mark.asyncio
async def test_qdrant_store_search_l0_uses_query_points(monkeypatch):
    client = FakeQdrantClient()
    client.query_points_response = SimpleNamespace(
        points=[
            SimpleNamespace(
                id="point-1",
                score=0.91,
                payload={
                    "id": "l0_abc",
                    "agent_id": "agent-1",
                    "message_text": "hello",
                },
            )
        ]
    )
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", lambda url: client)
    store = QdrantStore(
        "http://qdrant.example:6333",
        3,
        l0_collection="agent_l0",
        l1_collection="agent_l1",
    )

    results = await store.search_l0("agent-1", [0.1, 0.2, 0.3], limit=7)

    call = client.query_points_calls[0]
    assert call["collection_name"] == "agent_l0"
    assert call["query"] == [0.1, 0.2, 0.3]
    assert call["limit"] == 7
    assert call["with_payload"] is True
    assert call["query_filter"].must[0].key == "agent_id"
    assert call["query_filter"].must[0].match.value == "agent-1"
    assert results == [
        {
            "id": "l0_abc",
            "score": 0.91,
            "agent_id": "agent-1",
            "message_text": "hello",
        }
    ]


@pytest.mark.asyncio
async def test_qdrant_store_search_l1_uses_query_points(monkeypatch):
    client = FakeQdrantClient()
    client.query_points_response = SimpleNamespace(
        points=[
            SimpleNamespace(
                id="point-1",
                score=0.87,
                payload={
                    "id": "mem_abc",
                    "agent_id": "agent-1",
                    "content": "User likes concise answers.",
                    "type": "instruction",
                },
            )
        ]
    )
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", lambda url: client)
    store = QdrantStore(
        "http://qdrant.example:6333",
        3,
        l0_collection="agent_l0",
        l1_collection="agent_l1",
    )

    results = await store.search_l1("agent-1", [0.4, 0.5, 0.6], limit=5)

    call = client.query_points_calls[0]
    assert call["collection_name"] == "agent_l1"
    assert call["query"] == [0.4, 0.5, 0.6]
    assert call["limit"] == 5
    assert call["with_payload"] is True
    assert call["query_filter"].must[0].key == "agent_id"
    assert call["query_filter"].must[0].match.value == "agent-1"
    assert results == [
        {
            "id": "mem_abc",
            "score": 0.87,
            "agent_id": "agent-1",
            "content": "User likes concise answers.",
            "type": "instruction",
        }
    ]


@pytest.mark.asyncio
async def test_qdrant_store_maps_l1_record_id_to_valid_point_id(monkeypatch):
    client = FakeQdrantClient()
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", lambda url: client)
    store = QdrantStore("http://qdrant.example:6333", 3)
    record = MemoryRecord(
        id="mem_abc123",
        agent_id="agent-1",
        content="User likes concise answers.",
        type="instruction",
    )

    await store.upsert_l1(record, [0.1, 0.2, 0.3])
    await store.delete_l1(record.id)

    point = client.upserts[0][1][0]
    uuid.UUID(str(point.id))
    assert point.id != record.id
    assert point.payload["id"] == record.id
    assert client.deletes[0][1].points == [point.id]
