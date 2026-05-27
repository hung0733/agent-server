from __future__ import annotations

import re

import pytest

import conftest


def test_tdai_memory_test_schema_safety_allows_prefixed_schema():
    assert conftest.is_safe_tdai_memory_test_schema("test_memories_abc")


@pytest.mark.parametrize(
    "schema",
    [
        "test_memories",
        "memories",
        "public",
        "test_memory_abc",
        "test_memories-bad",
        "test_memories.bad",
        "test_memories_",
    ],
)
def test_tdai_memory_test_schema_safety_rejects_unsafe_schema(schema):
    assert not conftest.is_safe_tdai_memory_test_schema(schema)


def test_make_tdai_memory_test_schema_uses_safe_unique_name(monkeypatch):
    monkeypatch.setattr(conftest.os, "getpid", lambda: 12345)

    schema = conftest.make_tdai_memory_test_schema("test_memories")

    assert re.fullmatch(r"test_memories_12345_[0-9a-f]{8}", schema)
    assert conftest.is_safe_tdai_memory_test_schema(schema)


class FakePostgresConn:
    def __init__(self):
        self.executed = []
        self.closed = False

    async def execute(self, query):
        self.executed.append(query)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_tdai_memory_test_schema_context_creates_and_drops_schema(monkeypatch):
    conns = []

    async def fake_connect(url):
        conn = FakePostgresConn()
        conns.append((url, conn))
        return conn

    monkeypatch.setattr(conftest.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(conftest.os, "getpid", lambda: 12345)
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: type("U", (), {"hex": "abcdef123456"})())

    async with conftest.tdai_memory_test_schema_context(
        base_schema="test_memories",
        postgres_url="postgresql://db/memory",
    ) as schema:
        assert schema == "test_memories_12345_abcdef12"

    assert [url for url, _ in conns] == [
        "postgresql://db/memory",
        "postgresql://db/memory",
    ]
    assert conns[0][1].executed == [
        'CREATE SCHEMA IF NOT EXISTS "test_memories_12345_abcdef12"'
    ]
    assert conns[1][1].executed == [
        'DROP SCHEMA IF EXISTS "test_memories_12345_abcdef12" CASCADE'
    ]
    assert conns[0][1].closed
    assert conns[1][1].closed


@pytest.mark.asyncio
async def test_tdai_memory_test_schema_context_refuses_to_drop_base_schema(monkeypatch):
    def fake_make_schema(base_schema=None):
        return "test_memories"

    monkeypatch.setattr(conftest, "make_tdai_memory_test_schema", fake_make_schema)

    with pytest.raises(ValueError):
        async with conftest.tdai_memory_test_schema_context(
            base_schema="test_memories",
            postgres_url="postgresql://db/memory",
        ):
            pass
