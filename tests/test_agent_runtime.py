import asyncio

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from backend.agent.agent import Agent
from backend.graph.agent import assign_task_node, chat_node, graph, route_after_chat
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
        return AIMessage(content="你好")


class FakeModels:
    def __init__(self, llm):
        self.llm = llm

    def getModel(self, level, is_sec=False):
        return self.llm

    def getSysActModel(self):
        return self.llm


class FakeSandbox:
    sandbox_id = "sandbox-1"

    async def run_command(self, command: str):
        return {"sandbox_id": self.sandbox_id, "result": {"exit_code": 0}}


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


@pytest.mark.asyncio
async def test_graph_routes_assign_task_tool_calls_through_assign_task_node():
    class ToolCallingLLM:
        def __init__(self):
            self.calls = 0
            self.bound_tools = None
            self.messages = []

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            self.messages.append(messages)
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "assign_task",
                            "args": {"task_json": '{"task":"demo"}'},
                            "id": "call-1",
                        }
                    ],
                )

            return AIMessage(content="done")

    llm = ToolCallingLLM()
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(llm),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
    )

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=config,
    )

    assert [tool.name for tool in llm.bound_tools] == ["assign_task"]
    assert llm.calls == 1
    assert isinstance(result["messages"][-1], ToolMessage)
    assert result["messages"][-1].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_assign_task_node_returns_tool_message():
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "assign_task",
                "args": {"task_json": '{"task":"demo"}'},
                "id": "call-1",
            }
        ],
    )

    result = await assign_task_node({"messages": [message]}, {"configurable": {}})

    assert len(result["messages"]) == 1
    assert result["messages"][0].tool_call_id == "call-1"
    assert '"tool_call_id": "call-1"' in result["messages"][0].content


@pytest.mark.asyncio
async def test_graph_routes_other_tool_calls_through_tools_node():
    class ToolCallingLLM:
        def __init__(self):
            self.calls = 0
            self.bound_tools = None
            self.messages = []

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            self.messages.append(messages)
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "run_command",
                            "args": {"command": "pwd"},
                            "id": "call-2",
                        }
                    ],
                )

            return AIMessage(content="done")

    llm = ToolCallingLLM()
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(llm),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
    )
    config["configurable"]["sandbox"] = FakeSandbox()

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=config,
    )

    assert [tool.name for tool in llm.bound_tools] == [
        "assign_task",
        "run_command",
        "write_file",
        "read_file",
        "list_files",
        "delete_file",
        "copy",
        "rename",
        "pwd",
        "cd",
    ]
    assert llm.calls == 2
    assert any(isinstance(message, ToolMessage) for message in llm.messages[1])
    assert result["messages"][-1].content == "done"
    assert result["messages"][-1].additional_kwargs["text_done"] is True


def test_route_after_chat_routes_assign_task_and_other_tool_calls():
    assign_task_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "assign_task",
                "args": {"task_json": "{}"},
                "id": "call-1",
            }
        ],
    )
    other_tool_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "run_command",
                "args": {"command": "pwd"},
                "id": "call-2",
            }
        ],
    )

    assert route_after_chat({"messages": [assign_task_message]}) == "assign_task"
    assert route_after_chat({"messages": [other_tool_message]}) == "tools"
    assert route_after_chat({"messages": [HumanMessage(content="hello")]}) == "__end__"


class FakeGraph:
    async def astream(self, payload, config, stream_mode):
        assert payload["messages"][0].content == "hello"
        assert config["configurable"]["thread_id"] == "session-1"
        assert stream_mode == "messages"
        yield (AIMessageChunk(content="he"), {"node": "chat"})
        yield AIMessage(content="llo", additional_kwargs={"text_done": True})


class FakeAgent:
    session_id = "session-1"
    models = object()
    sys_prompt = ""
    sender_agent_name = "user"
    recv_agent_name = "agent"
    stm_trigger_token = 10000
    stm_summary_token = 5000


@pytest.mark.asyncio
async def test_prepare_sys_prompt_defaults_to_empty_string():
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

    assert agent.sys_prompt == ""


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

    assert [chunk.chunk_type for chunk in chunks] == ["content", "content", "text_end"]
    assert [chunk.content for chunk in chunks] == ["he", "llo", None]


@pytest.mark.asyncio
async def test_chat_node_logs_content_lengths_and_tool_chunks(monkeypatch):
    calls = []

    class LoggingLLM:
        async def ainvoke(self, messages):
            return AIMessage(
                content="hello",
                tool_calls=[
                    {
                        "name": "search",
                        "args": {"query": "hello"},
                        "id": "call-1",
                    }
                ],
            )

    monkeypatch.setattr("backend.graph.graph_node.logger.info", lambda *args: calls.append(args))
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(LoggingLLM()),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)

    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "hello"
    assert calls == [
        ("Agent graph chat node 收到 content chunk：content_length=%s", 5),
        ("Agent graph chat node 收到工具調用：tool_name=%s", "search"),
    ]


def test_stream_chunks_to_content_joins_content_only():
    content = GraphNode.stream_chunks_to_content(
        [
            StreamChunk(chunk_type="think", content="reason"),
            StreamChunk(chunk_type="content", content="he"),
            StreamChunk(chunk_type="tool", content="search"),
            StreamChunk(chunk_type="content", content="llo"),
            StreamChunk(chunk_type="done"),
        ]
    )

    assert content == "hello"


def test_stream_chunks_to_message_preserves_ai_message_fields():
    message = GraphNode.stream_chunks_to_message(
        [
            StreamChunk(chunk_type="think", content="rea"),
            StreamChunk(chunk_type="think", content="son"),
            StreamChunk(chunk_type="content", content="he"),
            StreamChunk(
                chunk_type="tool",
                data={
                    "tool_call": {
                        "id": "call-1",
                        "name": "search",
                        "args": {"query": "hello"},
                    }
                },
            ),
            StreamChunk(chunk_type="content", content="llo"),
        ]
    )

    assert isinstance(message, AIMessage)
    assert message.content == "hello"
    assert message.additional_kwargs["reasoning_content"] == "reason"
    assert message.tool_calls == [
        {"name": "search", "args": {"query": "hello"}, "id": "call-1", "type": "tool_call"}
    ]


def test_stream_chunks_to_message_parses_openai_tool_call_arguments():
    message = GraphNode.stream_chunks_to_message(
        [
            StreamChunk(
                chunk_type="tool",
                data={
                    "id": "call-1",
                    "function": {"name": "search", "arguments": "{\"query\": \"hello\"}"},
                },
            )
        ]
    )

    assert isinstance(message, AIMessage)
    assert message.tool_calls == [
        {"name": "search", "args": {"query": "hello"}, "id": "call-1", "type": "tool_call"}
    ]


def test_stream_chunks_to_message_returns_tool_message():
    message = GraphNode.stream_chunks_to_message(
        [
            StreamChunk(
                chunk_type="tool_result",
                content="result",
                data={"tool_call_id": "call-1"},
            )
        ]
    )

    assert isinstance(message, ToolMessage)
    assert message.content == "result"
    assert message.tool_call_id == "call-1"


def test_stream_chunks_to_message_requires_tool_call_id_for_tool_result():
    with pytest.raises(ValueError, match="tool_call_id"):
        GraphNode.stream_chunks_to_message(
            [StreamChunk(chunk_type="tool_result", content="result")]
        )


def test_stream_chunks_to_message_rejects_non_object_tool_arguments():
    with pytest.raises(ValueError, match="arguments"):
        GraphNode.stream_chunks_to_message(
            [
                StreamChunk(
                    chunk_type="tool",
                    data={
                        "id": "call-1",
                        "function": {"name": "search", "arguments": "[]"},
                    },
                )
            ]
        )


@pytest.mark.asyncio
async def test_chat_node_preserves_reasoning_and_tool_calls():
    class ToolLLM:
        async def ainvoke(self, messages):
            return AIMessage(
                content="hello",
                additional_kwargs={"reasoning_content": "reason"},
                tool_calls=[
                    {
                        "name": "search",
                        "args": {"query": "hello"},
                        "id": "call-1",
                    }
                ],
            )

    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(ToolLLM()),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)
    message = result["messages"][0]

    assert isinstance(message, AIMessage)
    assert message.content == "hello"
    assert message.additional_kwargs["reasoning_content"] == "reason"
    assert message.additional_kwargs["text_done"] is True
    assert message.tool_calls == [
        {"name": "search", "args": {"query": "hello"}, "id": "call-1", "type": "tool_call"}
    ]
