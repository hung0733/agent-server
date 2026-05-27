import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from tdai_memory.models import L0Record
from tdai_memory.store.postgres import PostgresStore, _jieba_tsquery


class FakeConn:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, *args):
        return self.row


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, row):
        self.row = row

    def acquire(self):
        return FakeAcquire(FakeConn(self.row))


class FakeExecuteConn:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))
        return "INSERT 0 1"


class FakeExecutePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_read_pipeline_state_converts_datetime_fields_to_iso_strings():
    now = datetime(2026, 5, 26, 2, 32, tzinfo=timezone.utc)
    store = PostgresStore("postgresql://example/db")
    store._pool = FakePool(
        {
            "agent_id": "agent-1",
            "session_key": "session-1",
            "conversation_count": 2,
            "last_extraction_time": now,
            "last_extraction_updated_time": now,
            "last_active_time": 1779762720000,
            "l2_pending_l1_count": 0,
            "warmup_threshold": 1,
            "l2_last_extraction_time": now,
        }
    )

    state = await store.read_pipeline_state("agent-1", "session-1")

    assert state is not None
    assert state.last_extraction_time == now.isoformat()
    assert state.last_extraction_updated_time == now.isoformat()
    assert state.l2_last_extraction_time == now.isoformat()


def test_jieba_tsquery_drops_punctuation_tokens():
    tsquery = _jieba_tsquery(
        "用户接受由 Moss 作为指挥中心，将任务路由给 Hermes（创意）和 Prometheus（策略）。"
    )

    assert "Moss" in tsquery
    assert "Hermes" in tsquery
    assert "Prometheus" in tsquery
    assert "（" not in tsquery
    assert "）" not in tsquery
    assert "。" not in tsquery


@pytest.mark.asyncio
async def test_upsert_l0_writes_metadata_json():
    conn = FakeExecuteConn()
    store = PostgresStore("postgresql://example/db")
    store._pool = FakeExecutePool(conn)
    record = L0Record(
        id="l0_1",
        agent_id="agent-1",
        session_key="session-1",
        role="user",
        message_text="你好",
        recorded_at="2026-05-26T02:21:37+00:00",
        timestamp=1779762096,
        metadata={
            "conversation_kind": "agent_to_agent",
            "sender_name": "Sender",
            "sender_type": "agent",
            "recv_name": "Receiver",
            "recv_type": "agent",
        },
    )

    assert await store.upsert_l0(record) is True

    query, args = conn.calls[0]
    assert "metadata_json" in query
    assert json.loads(args[6]) == record.metadata
