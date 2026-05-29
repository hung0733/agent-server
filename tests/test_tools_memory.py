from __future__ import annotations

import pytest
from langgraph.prebuilt import ToolRuntime

from backend.i18n import t


class FakeSearchResult:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.total = payload.get("total", 0)

    def model_dump(self) -> dict:
        return self.payload


class FakeMemoryManager:
    def __init__(self) -> None:
        self.memory_calls: list[dict] = []
        self.conversation_calls: list[dict] = []

    async def search_memories(self, **kwargs):
        self.memory_calls.append(kwargs)
        return FakeSearchResult({"text": "memory result", "total": 1})

    async def search_conversations(self, **kwargs):
        self.conversation_calls.append(kwargs)
        return FakeSearchResult({"text": "conversation result", "total": 1})


def _runtime(configurable: dict) -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=None,
        config={"configurable": configurable},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )


def test_memory_search_schema_exposes_only_llm_arguments():
    from backend.tools.memory import tdai_memory_search

    schema = tdai_memory_search.args_schema.model_json_schema()

    assert tdai_memory_search.description == t("tools.memory.search.description")
    assert set(schema["properties"]) == {
        "query",
        "top_k",
        "strategy",
        "score_threshold",
        "type_filter",
        "scene_filter",
    }
    assert schema["required"] == ["query"]
    assert "runtime" not in schema["properties"]


def test_conversation_search_schema_exposes_only_llm_arguments():
    from backend.tools.memory import tdai_conversation_search

    schema = tdai_conversation_search.args_schema.model_json_schema()

    assert tdai_conversation_search.description == t(
        "tools.memory.conversation_search.description"
    )
    assert set(schema["properties"]) == {
        "query",
        "top_k",
        "strategy",
        "current_session_only",
    }
    assert schema["required"] == ["query", "current_session_only"]
    assert "runtime" not in schema["properties"]


@pytest.mark.asyncio
async def test_memory_search_uses_runtime_agent_id(monkeypatch):
    from backend.tools import memory as memory_tools

    manager = FakeMemoryManager()
    monkeypatch.setattr(memory_tools.MemoryManager, "instance", lambda: manager)

    result = await memory_tools.tdai_memory_search.coroutine(
        "偏好",
        _runtime({"agent_id": "agent-1", "thread_id": "session-1"}),
        top_k=3,
        strategy="keyword",
        score_threshold=0.1,
        type_filter="persona",
        scene_filter="work",
    )

    assert result == {"text": "memory result", "total": 1}
    assert manager.memory_calls == [
        {
            "agent_id": "agent-1",
            "query": "偏好",
            "top_k": 3,
            "strategy": "keyword",
            "score_threshold": 0.1,
            "type_filter": "persona",
            "scene_filter": "work",
        }
    ]


@pytest.mark.asyncio
async def test_conversation_search_uses_runtime_agent_id_and_thread_id(monkeypatch):
    from backend.tools import memory as memory_tools

    manager = FakeMemoryManager()
    monkeypatch.setattr(memory_tools.MemoryManager, "instance", lambda: manager)

    result = await memory_tools.tdai_conversation_search.coroutine(
        "上次討論",
        _runtime({"agent_id": "agent-1", "thread_id": "session-1"}),
        current_session_only=True,
        top_k=2,
        strategy="embedding",
    )

    assert result == {"text": "conversation result", "total": 1}
    assert manager.conversation_calls == [
        {
            "agent_id": "agent-1",
            "query": "上次討論",
            "top_k": 2,
            "strategy": "embedding",
            "session_key": "session-1",
        }
    ]


@pytest.mark.asyncio
async def test_conversation_search_can_search_all_agent_conversations(monkeypatch):
    from backend.tools import memory as memory_tools

    manager = FakeMemoryManager()
    monkeypatch.setattr(memory_tools.MemoryManager, "instance", lambda: manager)

    await memory_tools.tdai_conversation_search.coroutine(
        "上次討論",
        _runtime({"agent_id": "agent-1", "thread_id": "session-1"}),
        current_session_only=False,
    )

    assert manager.conversation_calls[0]["session_key"] is None
