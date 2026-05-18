import asyncio

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from backend.agent.agent import Agent
from backend.graph.agent import chat_node
from backend.graph.graph_node import GraphNode
from backend.llm.types import StreamChunk


class FakeLLM:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        self.started.set()
        await self.release.wait()
        return [StreamChunk(chunk_type="content", content="你好")]


class FakeModels:
    def __init__(self, llm):
        self.llm = llm

    def getSysActModel(self):
        return self.llm


@pytest.mark.asyncio
async def test_chat_node_waits_for_llm_and_returns_ai_message():
    llm = FakeLLM()
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(llm),
        sys_prompt="system prompt",
        involves_secrets=False,
        think_mode=True,
        args={"source": "test"},
    )

    task = asyncio.create_task(
        chat_node({"messages": [HumanMessage(content="你好")]}, config)
    )
    await asyncio.wait_for(llm.started.wait(), timeout=1)

    assert not task.done()
    assert isinstance(llm.messages[0], SystemMessage)
    assert isinstance(llm.messages[1], HumanMessage)

    llm.release.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "你好"


class FakeGraph:
    async def astream(self, payload, config, stream_mode):
        assert payload["messages"][0].content == "hello"
        assert config["configurable"]["thread_id"] == "session-1"
        assert stream_mode == "messages"
        yield (AIMessageChunk(content="he"), {"node": "chat"})
        yield AIMessage(content="llo")


class FakeAgent:
    session_id = "session-1"
    models = object()
    sys_prompt = ""
    sender_agent_name = "user"
    recv_agent_name = "agent"
    stm_trigger_token = 10000
    stm_summary_token = 5000


@pytest.mark.asyncio
async def test_prepare_sys_prompt_loads_selected_memory_blocks(monkeypatch):
    calls = []

    class FakeSessionFactory:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeMemoryBlockDAO:
        def __init__(self, session):
            calls.append(("session", session))

        async def list_by_agent_id_and_memory_types(self, agent_id, memory_types):
            calls.append(("query", agent_id, memory_types))
            return [
                type("MemoryBlock", (), {"memory_type": "SYS_PROMPT", "content": "\n\nsystem\n\n"})(),
                type("MemoryBlock", (), {"memory_type": "USER_PROFILE", "content": None})(),
                type("MemoryBlock", (), {"memory_type": "SOUL", "content": "\n\nsoul\n\n"})(),
            ]

    monkeypatch.setattr(
        "backend.agent.agent.async_session_factory", lambda: FakeSessionFactory()
    )
    monkeypatch.setattr("backend.agent.agent.MemoryBlockDAO", FakeMemoryBlockDAO)

    agent = Agent(
        1,
        2,
        3,
        "user-1",
        "agent-1",
        "session-1",
        "assistant",
        "agent",
        "user",
    )

    await agent.prepare_sys_prompt()

    assert calls[1] == (
        "query",
        2,
        ("SOUL", "USER_PROFILE", "IDENTITY", "SYS_PROMPT"),
    )
    assert agent.sys_prompt == "<SOUL>\nsoul\n</SOUL>\n\nsystem"
    assert "\n\n\n" not in agent.sys_prompt


@pytest.mark.asyncio
async def test_agent_proc_send_streams_content_chunks():
    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeAgent(),
            message="hello",
            think_mode=False,
            metadata={"source": "test"},
            graph=FakeGraph(),
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == ["content", "content"]
    assert [chunk.content for chunk in chunks] == ["he", "llo"]


@pytest.mark.asyncio
async def test_chat_node_logs_content_lengths_and_tool_chunks(monkeypatch):
    calls = []

    class LoggingLLM:
        async def ainvoke(self, messages):
            return [
                StreamChunk(chunk_type="content", content="he"),
                StreamChunk(chunk_type="tool", content="search"),
                StreamChunk(chunk_type="tool_result", content="result"),
                StreamChunk(chunk_type="content", content="llo"),
            ]

    monkeypatch.setattr("backend.graph.agent.logger.info", lambda *args: calls.append(args))
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(LoggingLLM()),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)

    assert result["messages"][0].content == "hello"
    assert calls == [
        ("Agent graph chat node 收到 content chunk：content_length=%s", 2),
        ("Agent graph chat node 收到工具調用：tool_name=%s", "search"),
        ("Agent graph chat node 收到工具結果：content_length=%s", 6),
        ("Agent graph chat node 收到 content chunk：content_length=%s", 3),
    ]
