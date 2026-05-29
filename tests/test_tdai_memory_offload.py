import json

import pytest

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.offload import manager as offload_manager


def test_parse_batch_summary_accepts_string_items():
    parsed = offload_manager._parse_batch_summary_content('["短摘要"]')

    results = []
    for item in parsed:
        if isinstance(item, str):
            results.append((item, 10))

    assert results == [("短摘要", 10)]


def test_parse_batch_summary_accepts_wrapped_results():
    parsed = offload_manager._parse_batch_summary_content(
        '{"results":[{"summary":"摘要","score":3}]}'
    )

    assert parsed == [{"summary": "摘要", "score": 3}]


@pytest.mark.asyncio
async def test_flush_pending_falls_back_to_result_text(tmp_path, monkeypatch):
    async def fail_summarize(*args, **kwargs):
        raise ValueError("boom")

    async def no_sleep(delay):
        return None

    monkeypatch.setattr(offload_manager, "_summarize_batch", fail_summarize)
    monkeypatch.setattr(offload_manager.asyncio, "sleep", no_sleep)

    manager = offload_manager.OffloadManager(
        str(tmp_path),
        llm_client=object(),
        config=MemoryConfig(),
    )
    agent_id = "agent-1"
    session_key = "session-1"
    await manager.initialize(agent_id)

    state = offload_manager.OffloadStateManager()
    state.add_tool_pair("tc-1", "tool", {"arg": "value"}, "重要工具結果")

    await manager._flush_pending(agent_id, session_key, state)

    jsonl_path = tmp_path / agent_id / "offload" / "offload.jsonl"
    entry = json.loads(jsonl_path.read_text().strip())
    assert entry["summary"] == "重要工具結果"
    assert entry["score"] == 10


@pytest.mark.asyncio
async def test_summarize_batch_falls_back_when_llm_returns_empty_content(monkeypatch):
    class FakeMessage:
        content = ""

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(offload_manager, "save_tdai_llm_usage", lambda *args: None)

    result = await offload_manager._summarize_batch(
        [("tc-1", "tool", {"arg": "value"}, "重要工具結果")],
        FakeClient(),
        MemoryConfig(),
    )

    assert result == [("重要工具結果", 10)]
