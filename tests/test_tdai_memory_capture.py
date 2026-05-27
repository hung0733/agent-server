from datetime import datetime, timezone

import pytest

from backend.tdai_memory.capture import perform_auto_capture
from backend.tdai_memory.models import CompletedTurn, ConversationMessage


class FakePostgres:
    def __init__(self):
        self.records = []
        self.runner_states = []

    def is_degraded(self):
        return False

    async def read_runner_state(self, agent_id, session_key):
        return None

    async def upsert_l0(self, record):
        self.records.append(record)
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


@pytest.mark.asyncio
async def test_capture_preserves_conversation_metadata_on_l0_records(tmp_path):
    postgres = FakePostgres()
    timestamp = int(datetime(2026, 5, 26, tzinfo=timezone.utc).timestamp() * 1000)
    metadata = {
        "conversation_kind": "agent_to_agent",
        "sender_name": "Sender",
        "sender_type": "agent",
        "recv_name": "Receiver",
        "recv_type": "agent",
    }
    turn = CompletedTurn(
        user_text="請處理呢個任務",
        assistant_text="收到",
        session_key="session-1",
        metadata=metadata,
        messages=[
            ConversationMessage(
                role="user",
                content="請處理呢個任務",
                timestamp=timestamp,
            ),
            ConversationMessage(
                role="assistant",
                content="收到",
                timestamp=timestamp + 1,
            ),
        ],
    )

    result = await perform_auto_capture(
        turn=turn,
        agent_id="agent-1",
        postgres=postgres,
        qdrant=None,
        embedding=None,
        data_dir=str(tmp_path),
    )

    assert result.l0_recorded_count == 2
    assert [record.metadata for record in postgres.records] == [metadata, metadata]
