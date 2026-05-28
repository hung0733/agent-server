from datetime import datetime, timezone

import pytest

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.manager import MemoryManager
from backend.tdai_memory.models import CompletedTurn, ConversationMessage


class FakePostgres:
    def __init__(self):
        self.rows = [
            {
                "id": "l0_1",
                "agent_id": "agent-1",
                "session_key": "session-1",
                "session_id": "",
                "role": "user",
                "message_text": "cached from db",
                "metadata": {},
                "recorded_at": "2026-05-28T00:00:00+00:00",
                "timestamp": 1779926400000,
            }
        ]
        self.query_count = 0
        self.runner_states = []

    def is_degraded(self):
        return False

    async def query_l0_for_l1(
        self,
        agent_id,
        session_key,
        after_recorded_at_epoch_ms=0,
        limit=100,
    ):
        self.query_count += 1
        return list(self.rows)

    async def read_runner_state(self, agent_id, session_key):
        return None

    async def upsert_l0(self, record):
        self.rows.append(record.model_dump())
        return True

    async def write_runner_state(
        self,
        agent_id,
        session_key,
        last_captured_timestamp,
        last_l1_cursor=None,
        last_scene_name="",
        round_index=0,
    ):
        self.runner_states.append(
            (agent_id, session_key, last_captured_timestamp, round_index)
        )
        return True


def make_manager(postgres):
    manager = MemoryManager(MemoryConfig())
    manager._postgres = postgres
    manager._offload = None
    manager._plugin_start_timestamp = 0
    manager._store_ready.set()
    return manager


@pytest.mark.asyncio
async def test_unified_timeline_uses_cache_after_first_db_load():
    postgres = FakePostgres()
    manager = make_manager(postgres)

    first = await manager.get_unified_timeline("agent-1", "session-1")
    second = await manager.get_unified_timeline("agent-1", "session-1")

    assert postgres.query_count == 1
    assert first == second


@pytest.mark.asyncio
async def test_capture_appends_l0_records_to_existing_timeline_cache(tmp_path):
    postgres = FakePostgres()
    manager = make_manager(postgres)
    await manager.get_unified_timeline("agent-1", "session-1")
    timestamp = int(datetime(2026, 5, 28, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
    turn = CompletedTurn(
        user_text="new message",
        assistant_text="new reply",
        session_key="session-1",
        messages=[
            ConversationMessage(role="user", content="new message", timestamp=timestamp),
            ConversationMessage(role="assistant", content="new reply", timestamp=timestamp + 1),
        ],
    )

    await manager.capture(agent_id="agent-1", turn=turn)
    timeline = await manager.get_unified_timeline("agent-1", "session-1")

    assert postgres.query_count == 1
    assert [item["content"] for item in timeline] == [
        "cached from db",
        "new message",
        "new reply",
    ]


@pytest.mark.asyncio
async def test_invalidating_timeline_cache_forces_next_db_load():
    postgres = FakePostgres()
    manager = make_manager(postgres)

    await manager.get_unified_timeline("agent-1", "session-1")
    await manager._invalidate_timeline_cache("agent-1", "session-1")
    await manager.get_unified_timeline("agent-1", "session-1")

    assert postgres.query_count == 2
