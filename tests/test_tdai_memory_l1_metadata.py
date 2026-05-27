import json

import pytest

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.pipeline.l1_extraction import run_l1_extraction


class FakePostgres:
    def __init__(self):
        self.saved = []

    async def query_l0_for_l1(
        self,
        agent_id,
        session_key,
        after_recorded_at_epoch_ms=0,
        limit=100,
    ):
        metadata = {
            "conversation_kind": "agent_to_agent",
            "sender_name": "Sender",
            "sender_type": "agent",
            "recv_name": "Receiver",
            "recv_type": "agent",
        }
        return [
            {
                "id": "l0_1",
                "agent_id": agent_id,
                "session_key": session_key,
                "session_id": "",
                "role": "user",
                "message_text": "請記住我負責設計任務。",
                "metadata": metadata,
            },
            {
                "id": "l0_2",
                "agent_id": agent_id,
                "session_key": session_key,
                "session_id": "",
                "role": "assistant",
                "message_text": "收到，我會記住。",
                "metadata": metadata,
            },
        ]

    async def query_l1_records(self, agent_id, limit=50):
        return []

    async def upsert_l1(self, record):
        self.saved.append(record)
        return True


class FakeQdrant:
    async def upsert_l1(self, record, embedding):
        return None


class FakeEmbedding:
    def is_ready(self):
        return False

    async def embed(self, text):
        return [0.1, 0.2, 0.3]


class FakeCompletions:
    async def create(self, **kwargs):
        content = json.dumps(
            {
                "memories": [
                    {
                        "content": "Sender 負責設計任務。",
                        "type": "persona",
                        "priority": 70,
                        "metadata": {"source": "test"},
                    }
                ]
            },
            ensure_ascii=False,
        )
        message = type("Message", (), {"content": content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class FakeChat:
    completions = FakeCompletions()


class FakeLLMClient:
    chat = FakeChat()


@pytest.mark.asyncio
async def test_l1_extraction_preserves_l0_conversation_metadata(monkeypatch, tmp_path):
    async def fake_batch_dedup(**kwargs):
        return kwargs["new_memories"]

    monkeypatch.setattr(
        "backend.tdai_memory.pipeline.l1_dedup.batch_dedup",
        fake_batch_dedup,
    )
    postgres = FakePostgres()

    memories = await run_l1_extraction(
        agent_id="agent-1",
        session_key="session-1",
        postgres=postgres,
        qdrant=FakeQdrant(),
        embedding=FakeEmbedding(),
        llm_client=FakeLLMClient(),
        config=MemoryConfig(),
        data_dir=str(tmp_path),
    )

    assert len(memories) == 1
    assert memories[0].metadata["source"] == "test"
    assert memories[0].metadata["conversation_kind"] == "agent_to_agent"
    assert memories[0].metadata["participants"] == {
        "sender": {"name": "Sender", "type": "agent"},
        "receiver": {"name": "Receiver", "type": "agent"},
    }
