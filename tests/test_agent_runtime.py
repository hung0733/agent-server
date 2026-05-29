import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.agent.agent import Agent
from backend.graph.agent import (
    chat_node,
    graph as agent_graph,
    route_after_chat as agent_route_after_chat,
)
from backend.graph.graph_node import GraphNode, MessageState
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.tdai_memory.models import RecallResult
from backend.tools.memory import MemoryTools
from backend.tools.sandbox import SandboxTools
from backend.tools.system import SystemTools


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


class FakeAssignTaskAsyncSession:
    def __init__(self):
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.committed = True


class FakeAssignedTaskDAO:
    created_data = None

    def __init__(self, session):
        self.session = session

    async def create(self, data):
        type(self).created_data = data
        return SimpleNamespace(id=99)

    async def create_initial_steps(self, *, task_db_id, assign_agent_id, step_ids):
        return [
            SimpleNamespace(step_id=step_ids[0], title="brainstorm", status="pending"),
            SimpleNamespace(step_id=step_ids[1], title="planning", status="blocked"),
            SimpleNamespace(step_id=step_ids[2], title="review", status="blocked"),
        ]


def _patch_assign_task_persistence(monkeypatch):
    fake_session = FakeAssignTaskAsyncSession()
    FakeAssignedTaskDAO.created_data = None
    monkeypatch.setattr(
        "backend.tools.system.async_session_factory",
        lambda: fake_session,
    )
    monkeypatch.setattr(
        "backend.tools.system.AssignedTaskDAO",
        FakeAssignedTaskDAO,
    )
    return fake_session


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
    assert any(
        isinstance(message, HumanMessage) and message.content == "你好"
        for message in llm.messages
    )

    llm.release.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "你好"


@pytest.mark.asyncio
async def test_chat_node_applies_runtime_model_args_before_binding_tools(monkeypatch):
    captured = {}

    class ToolBindingLLM(ChatOpenAI):
        def bind_tools(self, tools):
            captured["model"] = self
            captured["tools"] = tools
            return BoundLLM()

    class BoundLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="你好")

    llm = ToolBindingLLM(
        api_key="test-key",
        base_url="http://example.com",
        model="qwen3.6-chat",
    )
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
        "tdai_memory_search",
        "tdai_conversation_search",
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
async def test_graph_binds_assign_task_through_tools_node(monkeypatch):
    class FakeMemoryManager:
        async def capture(self, *, agent_id, turn):
            return None

    monkeypatch.setattr(
        "backend.graph.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    class ToolCallingLLM:
        def __init__(self):
            self.bound_tools = None

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages):
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

    result = await agent_graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=config,
    )

    assert [tool.name for tool in llm.bound_tools] == [
        "tdai_memory_search",
        "tdai_conversation_search",
    ]
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_graph_binds_assign_task_when_system_tools_enabled():
    class ToolCallingLLM:
        def __init__(self):
            self.bound_tools = None

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="done")

    llm = ToolCallingLLM()
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(llm),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        enable_system_tools=True,
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)

    assert [tool.name for tool in llm.bound_tools] == [
        "tdai_memory_search",
        "tdai_conversation_search",
        "assign_task",
    ]
    assert result["messages"][-1].content == "done"


def test_prepare_chat_node_config_includes_agent_db_id_for_assign_task():
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=FakeModels(FakeLLM()),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        agent_db_id=2,
    )

    assert config["configurable"]["agent_db_id"] == 2


@pytest.mark.asyncio
async def test_graph_routes_other_tool_calls_through_tools_node(monkeypatch):
    class FakeMemoryManager:
        async def capture(self, *, agent_id, turn):
            return None

    monkeypatch.setattr(
        "backend.graph.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

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
        "tdai_memory_search",
        "tdai_conversation_search",
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
    assert agent_route_after_chat({"messages": [HumanMessage(content="hello")]}) == "end_node"


@pytest.mark.asyncio
async def test_system_enabled_graph_executes_assign_task_tool_call(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)

    class ToolCallingLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "assign_task",
                        "args": {
                            "task_name": "Task tracker",
                            "goal": "Create root task tracking",
                        },
                        "id": "call-1",
                    }
                ],
            )

    graph = StateGraph(MessageState)
    graph.add_node("chat", chat_node)
    graph.add_node("tools", ToolNode(SystemTools + MemoryTools + SandboxTools))
    graph.add_edge(START, "chat")
    graph.add_conditional_edges("chat", agent_route_after_chat)
    graph.add_edge("tools", END)
    app = graph.compile()

    result = await app.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=GraphNode.prepare_chat_node_config(
            thread_id="session-1",
            models=FakeModels(ToolCallingLLM()),
            sys_prompt="",
            involves_secrets=False,
            think_mode=False,
            args={},
            user_db_id=123,
            agent_db_id=456,
            enable_system_tools=True,
        ),
    )

    output = json.loads(result["messages"][-1].content)
    assert output["accepted"] is True
    assert output["task_name"] == "Task tracker"
    assert fake_session.committed is True
    assert FakeAssignedTaskDAO.created_data.user_id == 123
    assert FakeAssignedTaskDAO.created_data.responsible_agent_id == 456


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
    agent_db_id = 2
    session_db_id = 3
    agent_id = "agent-1"
    session_id = "session-1"
    models = object()
    sys_prompt = ""
    sender_agent_name = "user"
    recv_agent_name = "agent"
    stm_trigger_token = 10000
    stm_summary_token = 5000

    async def prepare_sys_prompt(self, mem_prompt: str):
        self.sys_prompt = mem_prompt


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
            return RecallResult()

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
    assert graph.configs[0]["configurable"]["agent_db_id"] == 2


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
        (t("graph.agent.chat_node_content_chunk_received"), 5),
        (t("graph.agent.chat_node_tool_chunk_received"), "search"),
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
