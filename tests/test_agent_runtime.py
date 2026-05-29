import asyncio

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from backend.agent.agent import Agent
from backend.graph.agent import (
    chat_node,
    graph as agent_graph,
    route_after_chat as agent_route_after_chat,
)
from backend.graph.graph_node import GraphNode
from backend.graph.bulter import (
    _get_allowed_agent_names,
    assign_task_node,
    graph as supervisor_graph,
    route_after_assign_task,
    route_after_chat as supervisor_route_after_chat,
)
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
        return 1, self.llm

    def getSysActModel(self):
        return self.llm


class FakeSandbox:
    sandbox_id = "sandbox-1"

    async def run_command(self, command: str):
        return {"sandbox_id": self.sandbox_id, "result": {"exit_code": 0}}


class FakeAsyncSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _chat_openai(model: str, extra_body=None) -> ChatOpenAI:
    return ChatOpenAI(
        api_key="test-key",
        base_url="http://example.com",
        model=model,
        extra_body=extra_body,
    )


def test_runtime_model_args_uses_non_thinking_defaults():
    model = _chat_openai("qwen3.6-chat")
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(model),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={"source": "test"},
    )

    bound = GraphNode.with_runtime_model_args(config, model)

    assert bound.temperature == 0.7
    assert bound.top_p == 0.8
    assert bound.presence_penalty == 1.5
    assert bound.extra_body == {
        "chat_template_kwargs": {"enable_thinking": False},
        "top_k": 20,
        "repetition_penalty": 1.0,
        "min_p": 0.0,
    }


def test_runtime_model_args_uses_thinking_defaults():
    model = _chat_openai("qwen3.6-chat")
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(model),
        sys_prompt="",
        involves_secrets=False,
        think_mode=True,
        args={},
    )

    bound = GraphNode.with_runtime_model_args(config, model)

    assert bound.temperature == 1.0
    assert bound.top_p == 0.95
    assert bound.presence_penalty == 1.5
    assert bound.extra_body == {
        "chat_template_kwargs": {"enable_thinking": True},
        "top_k": 20,
        "repetition_penalty": 1.0,
        "min_p": 0.0,
    }


def test_runtime_model_args_only_defaults_for_qwen36_models():
    model = _chat_openai("gpt-4.1-mini")
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(model),
        sys_prompt="",
        involves_secrets=False,
        think_mode=True,
        args={},
    )

    assert GraphNode.with_runtime_model_args(config, model) is model


def test_runtime_model_args_still_applies_explicit_args_for_other_models():
    model = _chat_openai("gpt-4.1-mini")
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(model),
        sys_prompt="",
        involves_secrets=False,
        think_mode=True,
        args={"temperature": 0.3, "top_k": 12, "source": "test"},
    )

    bound = GraphNode.with_runtime_model_args(config, model)

    assert bound.temperature == 0.3
    assert bound.extra_body == {"top_k": 12}


def test_runtime_model_args_allows_args_to_override_defaults_and_preserves_zero():
    model = _chat_openai("qwen3.6-chat", extra_body={"existing": True, "top_k": 99})
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(model),
        sys_prompt="",
        involves_secrets=False,
        think_mode=True,
        args={
            "temperature": 0,
            "top_p": 0.5,
            "presence_penalty": None,
            "top_k": 0,
            "repetition_penalty": 1.2,
            "min_p": 0.0,
            "source": "test",
        },
    )

    bound = GraphNode.with_runtime_model_args(config, model)

    assert bound.temperature == 0
    assert bound.top_p == 0.5
    assert bound.presence_penalty == 1.5
    assert bound.extra_body == {
        "existing": True,
        "chat_template_kwargs": {"enable_thinking": True},
        "top_k": 0,
        "repetition_penalty": 1.2,
        "min_p": 0.0,
    }


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
async def test_chat_node_applies_runtime_model_args_before_binding_tools(monkeypatch):
    captured = {}

    class BoundLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="你好")

    def fake_bind_tools(model, tools):
        captured["model"] = model
        captured["tools"] = tools
        return BoundLLM()

    monkeypatch.setattr("backend.graph.agent._bind_tools", fake_bind_tools)
    llm = _chat_openai("qwen3.6-chat")
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(llm),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={"temperature": 0.2, "top_k": 10},
    )
    config["configurable"]["sandbox"] = FakeSandbox()

    result = await chat_node({"messages": [HumanMessage(content="你好")]}, config)

    assert isinstance(result["messages"][0], AIMessage)
    assert [tool.name for tool in captured["tools"]] == [
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
    assert captured["model"].temperature == 0.2
    assert captured["model"].top_p == 0.8
    assert captured["model"].presence_penalty == 1.5
    assert captured["model"].extra_body == {
        "chat_template_kwargs": {"enable_thinking": False},
        "top_k": 10,
        "repetition_penalty": 1.0,
        "min_p": 0.0,
    }
    assert captured["messages"]


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
                            "args": {
                                "task_json": '{"state":"request","agent":"Hephaestus","mission":"整打卡 web"}'
                            },
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
    config["configurable"]["assign_task_allowed_agent_names"] = ["Hephaestus"]

    result = await supervisor_graph.ainvoke(
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
                "args": {
                    "task_json": '{"state":"request","agent":"Hephaestus","mission":"整打卡 web"}'
                },
                "id": "call-1",
            }
        ],
    )

    result = await assign_task_node(
        {"messages": [message]},
        {"configurable": {"assign_task_allowed_agent_names": ["Hephaestus"]}},
    )

    assert len(result["messages"]) == 1
    assert result["messages"][0].tool_call_id == "call-1"
    assert '"tool_call_id": "call-1"' in result["messages"][0].content
    assert '"accepted": true' in result["messages"][0].content


@pytest.mark.asyncio
async def test_graph_retries_invalid_assign_task_payload():
    class RetryingLLM:
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
                            "args": {"task_json": '{"title":"wrong shape"}'},
                            "id": "call-1",
                        }
                    ],
                )

            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "assign_task",
                        "args": {
                            "task_json": '{"state":"request","agent":"Hephaestus","mission":"整打卡 web"}'
                        },
                        "id": "call-2",
                    }
                ],
            )

    llm = RetryingLLM()
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(llm),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
    )
    config["configurable"]["assign_task_allowed_agent_names"] = ["Hephaestus"]

    result = await supervisor_graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=config,
    )

    assert llm.calls == 2
    assert any(isinstance(message, ToolMessage) for message in llm.messages[1])
    assert isinstance(result["messages"][-1], ToolMessage)
    assert result["messages"][-1].tool_call_id == "call-2"
    assert '"accepted": true' in result["messages"][-1].content


def test_route_after_assign_task_stops_after_retry_limit():
    rejected_messages = [
        ToolMessage(content='{"accepted": false}', tool_call_id=f"call-{i}")
        for i in range(3)
    ]

    assert route_after_assign_task({"messages": rejected_messages[:1]}) == "chat"
    assert route_after_assign_task({"messages": rejected_messages[:2]}) == "chat"
    assert route_after_assign_task({"messages": rejected_messages}) == "__end__"


@pytest.mark.asyncio
async def test_get_allowed_agent_names_loads_active_user_agent_names(monkeypatch):
    class FakeAgentDAO:
        def __init__(self, session):
            self.session = session

        async def list_by_user_id(self, user_id):
            assert user_id == 123
            return [
                type("AgentObj", (), {"name": "Hephaestus", "is_active": True})(),
                type("AgentObj", (), {"name": "OldAgent", "is_active": False})(),
            ]

    monkeypatch.setattr("backend.graph.supervisor.AgentDAO", FakeAgentDAO)
    monkeypatch.setattr(
        "backend.graph.supervisor.async_session_factory",
        lambda: FakeAsyncSessionContext(),
    )

    names = await _get_allowed_agent_names({"configurable": {"user_db_id": 123}})

    assert names == ["Hephaestus"]


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

    result = await agent_graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=config,
    )

    assert [tool.name for tool in llm.bound_tools] == [
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


def test_agent_route_after_chat_routes_tool_calls_to_tools_node():
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

    assert agent_route_after_chat({"messages": [assign_task_message]}) == "tools"
    assert agent_route_after_chat({"messages": [other_tool_message]}) == "tools"
    assert (
        agent_route_after_chat({"messages": [HumanMessage(content="hello")]})
        == "__end__"
    )


def test_supervisor_route_after_chat_routes_assign_task_to_assign_task_node():
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

    assert (
        supervisor_route_after_chat({"messages": [assign_task_message]})
        == "assign_task"
    )
    assert supervisor_route_after_chat({"messages": [other_tool_message]}) == "tools"
    assert (
        supervisor_route_after_chat({"messages": [HumanMessage(content="hello")]})
        == "__end__"
    )


class FakeGraph:
    configs = []

    async def astream(self, payload, config, stream_mode):
        assert payload["messages"][0].content == "hello"
        assert config["configurable"]["thread_id"] == "session-1"
        self.configs.append(config)
        assert stream_mode == "messages"
        yield (AIMessageChunk(content="he"), {"node": "chat"})
        yield AIMessage(content="llo", additional_kwargs={"text_done": True})


class FakeAgent:
    user_db_id = 1
    agent_id = "agent-1"
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

    await agent.prepare_sys_prompt("")

    assert agent.sys_prompt == ""


def test_agent_runtime_marks_user_to_agent_conversation():
    agent = Agent(
        1,
        2,
        3,
        "user-1",
        "agent-1",
        "session-1",
        "assistant",
        "Receiver",
        None,
        "Alice",
    )

    assert agent.sender_type == "user"
    assert agent.recv_type == "agent"
    assert agent.conversation_kind == "user_to_agent"


def test_agent_runtime_marks_agent_to_agent_conversation():
    agent = Agent(
        1,
        2,
        3,
        "user-1",
        "agent-1",
        "session-1",
        "assistant",
        "Receiver",
        99,
        "Sender",
    )

    assert agent.sender_type == "agent"
    assert agent.recv_type == "agent"
    assert agent.conversation_kind == "agent_to_agent"


@pytest.mark.asyncio
async def test_agent_proc_send_streams_content_chunks(monkeypatch):
    recall_calls = []
    sandbox = FakeSandbox()

    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            recall_calls.append((agent_id, session_key, user_text))

    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    graph = FakeGraph()
    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeAgent(),
            message="hello",
            think_mode=False,
            metadata={"source": "test"},
            sandbox=sandbox,
            graph=graph,
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == ["content", "content", "text_end"]
    assert [chunk.content for chunk in chunks] == ["he", "llo", None]
    assert recall_calls == [("agent-1", "session-1", "hello")]
    assert graph.configs[0]["configurable"]["conversation_kind"] == "user_to_agent"
    assert graph.configs[0]["configurable"]["sender_type"] == "user"
    assert graph.configs[0]["configurable"]["sandbox"] is sandbox


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

    monkeypatch.setattr(
        "backend.graph.graph_node.logger.info", lambda *args: calls.append(args)
    )
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
        {
            "name": "search",
            "args": {"query": "hello"},
            "id": "call-1",
            "type": "tool_call",
        }
    ]


def test_stream_chunks_to_message_parses_openai_tool_call_arguments():
    message = GraphNode.stream_chunks_to_message(
        [
            StreamChunk(
                chunk_type="tool",
                data={
                    "id": "call-1",
                    "function": {"name": "search", "arguments": '{"query": "hello"}'},
                },
            )
        ]
    )

    assert isinstance(message, AIMessage)
    assert message.tool_calls == [
        {
            "name": "search",
            "args": {"query": "hello"},
            "id": "call-1",
            "type": "tool_call",
        }
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
        {
            "name": "search",
            "args": {"query": "hello"},
            "id": "call-1",
            "type": "tool_call",
        }
    ]
