from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.agent import Agent


class _BlockingModel:
    def __init__(self, release_event: asyncio.Event):
        self.release_event = release_event
        self.calls = 0

    def bind(self, **_kwargs):
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        await self.release_event.wait()
        return AIMessage(content="- summary item")


class _FakeGraph:
    def __init__(self, messages):
        self.messages = messages
        self.aupdate_state = AsyncMock()

    async def aget_state(self, _config):
        return SimpleNamespace(values={"messages": self.messages, "summary": ""})


@pytest.mark.asyncio
async def test_proc_review_stm_skips_concurrent_same_session(monkeypatch):
    agent = Agent(
        agent_db_id=str(uuid4()),
        session_db_id=str(uuid4()),
        agent_id="agent-1",
        session_id="session-1",
        involves_secrets=False,
        name="Tester",
    )
    agent.stm_trigger_token = 1
    agent.stm_summary_token = 1

    release_event = asyncio.Event()
    model = _BlockingModel(release_event)
    graph = _FakeGraph(
        [
            HumanMessage(id="m1", content="hello"),
            AIMessage(id="m2", content="world"),
        ]
    )
    model_set = SimpleNamespace(
        level={
            2: [SimpleNamespace(id=uuid4(), api_key_encrypted=None, base_url="http://x", model_name="m2")],
            1: [],
        }
    )

    monkeypatch.setattr("agent.agent.build_streaming_chat_openai", lambda **_kwargs: model)
    monkeypatch.setattr("agent.agent.LLMEndpointDAO.record_feedback", AsyncMock())
    monkeypatch.setattr("agent.agent.Tools.get_token_count", lambda _text: 10)

    def _discard_coro(coro):
        coro.close()
        return None

    monkeypatch.setattr("agent.agent.Tools.start_async_task", _discard_coro)

    task1 = asyncio.create_task(agent._proc_review_stm(graph, model_set))
    await asyncio.sleep(0)
    task2 = asyncio.create_task(agent._proc_review_stm(graph, model_set))
    await asyncio.sleep(0)

    release_event.set()
    await asyncio.gather(task1, task2)

    assert model.calls == 1
    graph.aupdate_state.assert_awaited_once()
