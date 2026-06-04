from datetime import datetime, timezone

import pytest

from backend.llm.types import StreamChunk
from backend.tdai_memory.capture import perform_auto_capture
from backend.tdai_memory.models import CompletedTurn, ConversationMessage


class FakePostgres:
    def __init__(self):
        self.records = []
        self.runner_states = []
        self.runner_state = None

    def is_degraded(self):
        return False

    async def read_runner_state(self, agent_id, session_key):
        return self.runner_state

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
        self.runner_state = {
            "agent_id": agent_id,
            "session_key": session_key,
            "last_captured_timestamp": last_captured_timestamp,
            "round_index": round_index,
        }
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
    assert result.l0_records == postgres.records
    assert postgres.runner_states == [
        ("agent-1", "session-1", timestamp + 1, 1)
    ]


@pytest.mark.asyncio
async def test_capture_runner_cursor_uses_message_timestamp_not_capture_time(tmp_path):
    postgres = FakePostgres()

    first_turn = CompletedTurn(
        user_text="",
        assistant_text="需要你確認一個問題",
        session_key="session-1",
        messages=[
            ConversationMessage(
                role="assistant",
                content="需要你確認一個問題",
                timestamp=1000,
            ),
        ],
    )
    first_result = await perform_auto_capture(
        turn=first_turn,
        agent_id="agent-1",
        postgres=postgres,
        qdrant=None,
        embedding=None,
        data_dir=str(tmp_path),
    )

    second_turn = CompletedTurn(
        user_text="只個人使用",
        assistant_text="",
        session_key="session-1",
        messages=[
            ConversationMessage(
                role="user",
                content="只個人使用",
                timestamp=1500,
            ),
        ],
    )
    second_result = await perform_auto_capture(
        turn=second_turn,
        agent_id="agent-1",
        postgres=postgres,
        qdrant=None,
        embedding=None,
        data_dir=str(tmp_path),
    )

    assert first_result.l0_recorded_count == 1
    assert second_result.l0_recorded_count == 1
    assert [record.message_text for record in postgres.records] == [
        "需要你確認一個問題",
        "只個人使用",
    ]
    assert postgres.runner_states == [
        ("agent-1", "session-1", 1000, 1),
        ("agent-1", "session-1", 1500, 2),
    ]


@pytest.mark.asyncio
async def test_capture_preserves_single_character_user_reply(tmp_path):
    postgres = FakePostgres()
    turn = CompletedTurn(
        user_text="1",
        assistant_text="",
        session_key="session-1",
        messages=[
            ConversationMessage(
                role="user",
                content="1",
                timestamp=1000,
            ),
            ConversationMessage(
                role="assistant",
                content="x",
                timestamp=1001,
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

    assert result.l0_recorded_count == 1
    assert postgres.records[0].role == "user"
    assert postgres.records[0].message_text == "1"
    assert postgres.runner_states == [
        ("agent-1", "session-1", 1000, 1),
    ]


@pytest.mark.asyncio
async def test_capture_discards_short_user_reply_when_rte_judges_noise(
    tmp_path, monkeypatch
):
    postgres = FakePostgres()

    class FakeRteModel:
        async def ainvoke(self, messages):
            return [StreamChunk(chunk_type="content", content="discard")]

        def get_resp_content(self, response):
            return response[0].content or ""

    async def get_rte_model():
        return FakeRteModel()

    monkeypatch.setattr(
        "backend.tdai_memory.capture.LLMSet.getRteModel",
        get_rte_model,
    )

    turn = CompletedTurn(
        user_text="嗯",
        assistant_text="請選擇資料來源。",
        session_key="session-1",
        messages=[
            ConversationMessage(
                role="assistant",
                content="請選擇資料來源。",
                timestamp=1000,
            ),
            ConversationMessage(
                role="user",
                content="嗯",
                timestamp=1001,
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

    assert result.l0_recorded_count == 1
    assert [record.role for record in postgres.records] == ["assistant"]


@pytest.mark.asyncio
async def test_capture_keeps_short_user_reply_when_rte_judges_meaningful(
    tmp_path, monkeypatch
):
    postgres = FakePostgres()

    class FakeRteModel:
        async def ainvoke(self, messages):
            return [StreamChunk(chunk_type="content", content="keep")]

        def get_resp_content(self, response):
            return response[0].content or ""

    async def get_rte_model():
        return FakeRteModel()

    monkeypatch.setattr(
        "backend.tdai_memory.capture.LLMSet.getRteModel",
        get_rte_model,
    )

    turn = CompletedTurn(
        user_text="1",
        assistant_text="請選擇資料來源。",
        session_key="session-1",
        messages=[
            ConversationMessage(
                role="assistant",
                content="請選擇資料來源。\n1. 官方名單\n2. 自訂名單",
                timestamp=1000,
            ),
            ConversationMessage(
                role="user",
                content="1",
                timestamp=1001,
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
    assert [record.role for record in postgres.records] == ["assistant", "user"]
    assert postgres.records[1].message_text == "1"
