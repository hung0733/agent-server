import asyncio
import base64
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
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, Interrupt

from backend.agent.agent import Agent
from backend.agent.butler import Bulter
from backend.graph.agent import (
    end_node as agent_end_node,
    chat_node,
    graph as agent_graph,
    route_after_chat as agent_route_after_chat,
)

from backend.graph.graph_node import GraphNode, MessageState
from backend.graph.brainstormer import (
    pre_submit_approval_node,
    pre_user_question_node,
    submit_approval_node,
)
from backend.graph.bulter import assign_task_node, workflow as butler_workflow
from backend.graph.interrupt_nodes import (
    APPROVE_LABEL,
    CANCEL_LABEL,
    OTHER_LABEL,
    _classify_approval_reply,
    human_review_node,
)
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.queues.message_queue import MsgQueueTask, TaskState
from backend.queues.msg_queue_handle import handle_agent_message
from backend.tdai_memory.models import RecallResult
from backend.tools.memory import MemoryTools
from backend.tools.sandbox import SandboxTools
from backend.tools.bulter import BulterTools


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


class FakeBrainstormerStepSession:
    commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        type(self).commits += 1


class FakeBrainstormerAssignedTaskDAO:
    updates = []

    def __init__(self, session):
        self.session = session

    async def update_step_output_html_by_session_id(self, **kwargs):
        type(self).updates.append(kwargs)


class FakeGraphNodeWhatsAppSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeGraphNodeUserAccDAO:
    user = None

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, id_):
        return type(self).user


class FakeGraphNodeAgentDAO:
    agent = None

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, id_):
        return type(self).agent


class FakeEvolutionWhatsAppChannel:
    instances = []

    def __init__(self, *, whatsapp_instance=None, whatsapp_key=None):
        self.whatsapp_instance = whatsapp_instance
        self.whatsapp_key = whatsapp_key
        self.sent = []
        self.closed = False
        type(self).instances.append(self)

    async def send_text(self, number, text):
        self.sent.append((number, text))
        return {"key": {"id": "msg-1"}}

    async def close(self):
        self.closed = True


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
    initial_steps_args = None

    def __init__(self, session):
        self.session = session

    async def create(self, data):
        type(self).created_data = data
        return SimpleNamespace(id=99)

    async def create_initial_steps(self, *, task_db_id, step_ids):
        type(self).initial_steps_args = (task_db_id, step_ids)
        return [
            SimpleNamespace(step_id=step_ids[0], title="brainstorm", status="pending"),
            SimpleNamespace(step_id=step_ids[1], title="planning", status="blocked"),
            SimpleNamespace(step_id=step_ids[2], title="review", status="blocked"),
        ]


def _patch_assign_task_persistence(monkeypatch):
    fake_session = FakeAssignTaskAsyncSession()
    FakeAssignedTaskDAO.created_data = None
    FakeAssignedTaskDAO.initial_steps_args = None
    monkeypatch.setattr(
        "backend.tools.bulter.async_session_factory",
        lambda: fake_session,
    )
    monkeypatch.setattr(
        "backend.tools.bulter.AssignedTaskDAO",
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
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)

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
async def test_graph_binds_assign_task_for_bulter_agent_type():
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
        agent_type="bulter",
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)

    assert [tool.name for tool in llm.bound_tools] == [
        "tdai_memory_search",
        "tdai_conversation_search",
        "assign_task",
        "list_assigned_tasks",
        "read_assigned_task",
    ]
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_graph_binds_brainstormer_tools_for_brainstormer_agent_type():
    class ToolCallingLLM:
        def __init__(self):
            self.bound_tools = None
            self.bound_tool_kwargs = None

        def bind_tools(self, tools, **kwargs):
            self.bound_tools = tools
            self.bound_tool_kwargs = kwargs
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
        agent_type="brainstormer",
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)

    assert [tool.name for tool in llm.bound_tools] == [
        "tdai_memory_search",
        "tdai_conversation_search",
        "ask_user_question",
        "submit_html_plan_for_approval",
    ]
    assert llm.bound_tool_kwargs == {"tool_choice": "required"}
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
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)

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
async def test_bulter_graph_executes_assign_task_tool_call(monkeypatch):
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
    graph.add_node("tools", ToolNode(BulterTools + MemoryTools + SandboxTools))
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
            agent_type="bulter",
        ),
    )

    output = json.loads(result["messages"][-1].content)
    assert output["accepted"] is True
    assert output["task_name"] == "Task tracker"
    assert fake_session.committed is True
    assert FakeAssignedTaskDAO.created_data.user_id == 123
    assert FakeAssignedTaskDAO.created_data.responsible_agent_id == 456


@pytest.mark.asyncio
async def test_bulter_graph_intercepts_assign_task_for_approval(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)

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

    app = butler_workflow.compile()

    result = await app.ainvoke(
        {"messages": [HumanMessage(content="幫我建立 task")]},
        config=GraphNode.prepare_chat_node_config(
            thread_id="session-1",
            models=FakeModels(ToolCallingLLM()),
            sys_prompt="",
            involves_secrets=False,
            think_mode=False,
            args={},
            user_db_id=123,
            agent_db_id=456,
            agent_type="bulter",
        ),
    )

    assert result["__interrupt__"][0].value["type"] == "human_review"
    assert result["human_review_node"] == "assign_task_node"
    assert result["human_review_data"] == {
        "task_name": "Task tracker",
        "goal": "Create root task tracking",
    }


@pytest.mark.asyncio
async def test_brainstormer_user_question_uses_tool_args_not_message_content(
    monkeypatch,
):
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)

    state = {
        "messages": [
            AIMessage(
                content="呢段 content 不應直接輸出。",
                tool_calls=[
                    {
                        "name": "ask_user_question",
                        "args": {
                            "question": "請確認名城資料來源。",
                            "description": "需要決定預載標準，因為資料表 seed、搜尋和爬蟲來源都會受影響。",
                            "choose": [
                                "採用日本城郭協會「日本100名城」作為固定 seed 名單。",
                                "先做自訂匯入流程，由用戶自行維護名單。",
                            ],
                        },
                        "id": "call-1",
                    }
                ],
            )
        ],
        "human_review_node": None,
        "human_review_data": None,
        "human_review_result": None,
    }
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=None,
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        agent_type="brainstormer",
    )

    result = await pre_user_question_node(state, config)

    content = result["messages"][0].content
    assert "呢段 content 不應直接輸出" not in content
    assert "請確認名城資料來源" in content
    assert "日本100名城" in content
    assert "自訂匯入流程" in content
    assert result["human_review_node"] == "chat"
    assert result["human_review_data"]["question"] == "請確認名城資料來源。"


@pytest.mark.asyncio
async def test_brainstormer_pre_submit_approval_uses_tool_args_not_message_content(
    monkeypatch,
):
    FakeBrainstormerStepSession.commits = 0
    FakeBrainstormerAssignedTaskDAO.updates = []
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)
    monkeypatch.setattr(
        "backend.graph.brainstormer.async_session_factory",
        lambda: FakeBrainstormerStepSession(),
    )
    monkeypatch.setattr(
        "backend.graph.brainstormer.AssignedTaskDAO",
        FakeBrainstormerAssignedTaskDAO,
    )

    html_plan = "<html><body><h1>計劃書</h1></body></html>"
    state = {
        "messages": [
            AIMessage(
                content="呢段 content 不應直接輸出。",
                tool_calls=[
                    {
                        "name": "submit_html_plan_for_approval",
                        "args": {
                            "task_id": "task-1",
                            "task_name": "名城資料整理",
                            "goal": "整理可審批的 HTML 計劃。",
                            "html_plan": html_plan,
                        },
                        "id": "call-1",
                    }
                ],
            )
        ],
        "human_review_node": None,
        "human_review_data": None,
        "human_review_result": None,
    }
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=None,
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        agent_type="brainstormer",
        session_db_id=321,
    )

    result = await pre_submit_approval_node(state, config)

    content = result["messages"][0].content
    assert "呢段 content 不應直接輸出" not in content
    assert "task-1" in content
    assert "名城資料整理" in content
    assert html_plan not in content
    whatsapp_document = result["messages"][0].additional_kwargs["whatsapp_document"]
    assert whatsapp_document["mediatype"] == "document"
    assert whatsapp_document["mimetype"] == "text/html"
    assert whatsapp_document["file_name"] == "名城資料整理.html"
    assert whatsapp_document["caption"] == content
    assert base64.b64decode(whatsapp_document["media"]).decode() == html_plan
    assert result["human_review_node"] == "submit_approval_node"
    assert result["human_review_data"]["html_plan"] == html_plan
    assert FakeBrainstormerAssignedTaskDAO.updates == [
        {"session_db_id": 321, "output_html": html_plan}
    ]
    assert FakeBrainstormerStepSession.commits == 1


def test_stream_interrupt_chunk_preserves_whatsapp_document_metadata():
    message = AIMessage(
        content="請查看附件 HTML 計劃書。",
        additional_kwargs={
            "whatsapp_document": {
                "media": "PGh0bWw+PC9odG1sPg==",
                "mimetype": "text/html",
                "file_name": "plan.html",
                "caption": "請查看附件 HTML 計劃書。",
            }
        },
    )

    chunk = Agent._stream_interrupt_chunk(
        {"__interrupt__": [Interrupt(value={"type": "human_review", "message": message})]}
    )

    assert chunk is not None
    assert chunk.chunk_type == "interrupt"
    assert chunk.data["message"] == "請查看附件 HTML 計劃書。"
    assert chunk.data["whatsapp_document"]["media"] == "PGh0bWw+PC9odG1sPg=="


@pytest.mark.asyncio
async def test_brainstormer_submit_approval_node_returns_approved_message(monkeypatch):
    sent = []

    async def fake_send_user_whatsapp(user_db_id, agent_db_id, content):
        sent.append((user_db_id, agent_db_id, content))
        return "msg-1"

    monkeypatch.setattr(GraphNode, "send_user_whatsapp", fake_send_user_whatsapp)

    state = {
        "messages": [HumanMessage(content="approve")],
        "human_review_node": "submit_approval_node",
        "human_review_data": {"html_plan": "<html></html>"},
        "human_review_result": APPROVE_LABEL,
    }
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=None,
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        agent_type="brainstormer",
        user_db_id=11,
        agent_db_id=22,
    )

    result = await submit_approval_node(state, config)

    assert result["messages"][0].content == t(
        "graph.brainstormer.submit_approval.approved_message"
    )
    assert sent == [
        (11, 22, t("graph.brainstormer.submit_approval.approved_message"))
    ]
    assert result["human_review_node"] is None
    assert result["human_review_data"] is None
    assert result["human_review_result"] is None


@pytest.mark.asyncio
async def test_graph_node_send_user_whatsapp_sends_text_and_closes(monkeypatch):
    FakeEvolutionWhatsAppChannel.instances = []
    FakeGraphNodeUserAccDAO.user = SimpleNamespace(phoneno="85261234567")
    FakeGraphNodeAgentDAO.agent = SimpleNamespace(
        whatsapp_instance="agent-instance",
        whatsapp_key="agent-key",
    )
    monkeypatch.setattr(
        "backend.graph.graph_node.async_session_factory",
        lambda: FakeGraphNodeWhatsAppSession(),
    )
    monkeypatch.setattr("backend.graph.graph_node.UserAccDAO", FakeGraphNodeUserAccDAO)
    monkeypatch.setattr("backend.graph.graph_node.AgentDAO", FakeGraphNodeAgentDAO)
    monkeypatch.setattr(
        "backend.graph.graph_node.EvolutionWhatsAppChannel",
        FakeEvolutionWhatsAppChannel,
    )

    message_id = await GraphNode.send_user_whatsapp(11, 22, "計劃書已核准")

    channel = FakeEvolutionWhatsAppChannel.instances[0]
    assert message_id == "msg-1"
    assert channel.whatsapp_instance == "agent-instance"
    assert channel.whatsapp_key == "agent-key"
    assert channel.sent == [("85261234567", "計劃書已核准")]
    assert channel.closed is True


@pytest.mark.asyncio
async def test_graph_node_send_user_whatsapp_skips_missing_fields(monkeypatch):
    FakeEvolutionWhatsAppChannel.instances = []
    FakeGraphNodeUserAccDAO.user = SimpleNamespace(phoneno=None)
    FakeGraphNodeAgentDAO.agent = SimpleNamespace(
        whatsapp_instance="agent-instance",
        whatsapp_key="agent-key",
    )
    monkeypatch.setattr(
        "backend.graph.graph_node.async_session_factory",
        lambda: FakeGraphNodeWhatsAppSession(),
    )
    monkeypatch.setattr("backend.graph.graph_node.UserAccDAO", FakeGraphNodeUserAccDAO)
    monkeypatch.setattr("backend.graph.graph_node.AgentDAO", FakeGraphNodeAgentDAO)
    monkeypatch.setattr(
        "backend.graph.graph_node.EvolutionWhatsAppChannel",
        FakeEvolutionWhatsAppChannel,
    )

    assert await GraphNode.send_user_whatsapp(None, 22, "計劃書已核准") is None
    assert await GraphNode.send_user_whatsapp(11, 22, "") is None
    assert await GraphNode.send_user_whatsapp(11, 22, "計劃書已核准") is None
    assert FakeEvolutionWhatsAppChannel.instances == []


@pytest.mark.asyncio
async def test_bulter_assign_task_node_persists_after_approval(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)

    state = {
        "messages": [
            HumanMessage(content="幫我建立 task"),
            AIMessage(
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
            ),
            HumanMessage(content="同意"),
        ],
        "human_review_node": "assign_task_node",
        "human_review_data": {
            "task_name": "Task tracker",
            "goal": "Create root task tracking",
        },
        "human_review_result": APPROVE_LABEL,
    }

    config = GraphNode.prepare_chat_node_config(
        thread_id="session-1",
        models=None,
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        user_db_id=123,
        agent_db_id=456,
        agent_type="bulter",
    )

    result = await assign_task_node(state, config)

    assert fake_session.committed is True
    created_data = FakeAssignedTaskDAO.created_data
    assert created_data.user_id == 123
    assert created_data.responsible_agent_id == 456
    assert created_data.task_name == "Task tracker"
    assert created_data.goal == "Create root task tracking"
    assert created_data.status == "brainstorm_pending"
    task_db_id, step_ids = FakeAssignedTaskDAO.initial_steps_args
    assert task_db_id == 99
    assert len(step_ids) == 3
    assert result["human_review_node"] is None
    assert result["human_review_data"] is None
    assert result["human_review_result"] is None
    assert "Task tracker" in result["messages"][0].content


@pytest.mark.asyncio
async def test_human_review_classifier_sends_user_message_to_llm(monkeypatch):
    calls = []

    class ApprovalClassifier:
        async def ainvoke(self, messages):
            calls.append(messages)
            return AIMessage(content="approve")

        def get_resp_content(self, response):
            return response.content

    async def get_approval_classifier():
        return ApprovalClassifier()

    monkeypatch.setattr(
        "backend.graph.interrupt_nodes.LLMSet.getRteModel",
        get_approval_classifier,
    )

    result = await _classify_approval_reply(
        [
            AIMessage(content="請確認任務。"),
            HumanMessage(content="同意"),
        ],
        {},
    )

    assert result == APPROVE_LABEL
    assert len(calls) == 1
    assert isinstance(calls[0][0], HumanMessage)
    assert "同意" in calls[0][0].content


@pytest.mark.asyncio
async def test_human_review_resume_stores_user_message(monkeypatch):
    stored_messages = []
    mirrored_messages = []

    monkeypatch.setattr(
        GraphNode,
        "store_message",
        lambda config, messages: stored_messages.append(list(messages)),
    )
    monkeypatch.setattr(
        GraphNode,
        "store_user_message",
        lambda config, messages: mirrored_messages.append(list(messages)),
    )

    graph = StateGraph(MessageState)
    graph.add_node("human_review_node", human_review_node)
    graph.add_edge(START, "human_review_node")
    graph.add_edge("human_review_node", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-review-store",
        models=None,
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        agent_id="agent-1",
        session_db_id=123,
        agent_type="brainstormer",
    )

    interrupted = await app.ainvoke(
        {
            "messages": [AIMessage(content="請選擇部署策略。")],
            "human_review_node": "chat",
            "human_review_data": {},
            "human_review_result": None,
            "human_review_approve": False,
        },
        config=config,
    )
    assert interrupted["__interrupt__"][0].value["type"] == "human_review"

    result = await app.ainvoke(
        Command(resume=HumanMessage(content="只個人使用")), config=config
    )

    assert result["human_review_result"] == APPROVE_LABEL
    assert len(stored_messages) == 1
    assert isinstance(stored_messages[0][0], AIMessage)
    assert isinstance(stored_messages[0][1], HumanMessage)
    assert stored_messages[0][1].content == "只個人使用"
    assert mirrored_messages == []


@pytest.mark.asyncio
async def test_human_review_resume_stores_and_mirrors_butler_user_message(monkeypatch):
    stored_messages = []
    mirrored_messages = []

    monkeypatch.setattr(
        GraphNode,
        "store_message",
        lambda config, messages: stored_messages.append(list(messages)),
    )
    monkeypatch.setattr(
        GraphNode,
        "store_user_message",
        lambda config, messages: mirrored_messages.append(list(messages)),
    )

    graph = StateGraph(MessageState)
    graph.add_node("human_review_node", human_review_node)
    graph.add_edge(START, "human_review_node")
    graph.add_edge("human_review_node", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = GraphNode.prepare_chat_node_config(
        thread_id="step-session-review-store",
        models=None,
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        agent_id="sub-agent-1",
        session_db_id=123,
        agent_type="brainstormer",
        sender_agent_db_id=456,
        sender_agent_id="parent-agent-1",
        sender_agent_session_db_id=789,
        sender_agent_session_id="parent-session-1",
        sender_is_sub_agent=False,
    )

    interrupted = await app.ainvoke(
        {
            "messages": [AIMessage(content="請確認。")],
            "human_review_node": "chat",
            "human_review_data": {},
            "human_review_result": None,
            "human_review_approve": False,
        },
        config=config,
    )
    assert interrupted["__interrupt__"][0].value["type"] == "human_review"

    result = await app.ainvoke(Command(resume=HumanMessage(content="2")), config=config)

    assert result["human_review_result"] == APPROVE_LABEL
    assert len(stored_messages) == 1
    assert len(mirrored_messages) == 1
    assert stored_messages[0][1].content == "2"
    assert mirrored_messages[0][1].content == "2"


@pytest.mark.asyncio
async def test_bulter_graph_resumes_assign_task_after_human_approval(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)

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

    class ApprovalClassifier:
        async def ainvoke(self, messages):
            return AIMessage(content="approve")

        def get_resp_content(self, response):
            return response.content

    async def get_approval_classifier():
        return ApprovalClassifier()

    monkeypatch.setattr(
        "backend.graph.interrupt_nodes.LLMSet.getRteModel",
        get_approval_classifier,
    )

    app = butler_workflow.compile(checkpointer=InMemorySaver())
    config = GraphNode.prepare_chat_node_config(
        thread_id="session-approve",
        models=FakeModels(ToolCallingLLM()),
        sys_prompt="",
        involves_secrets=False,
        think_mode=False,
        args={},
        user_db_id=123,
        agent_db_id=456,
        agent_type="bulter",
    )

    interrupted = await app.ainvoke(
        {"messages": [HumanMessage(content="幫我建立 task")]},
        config=config,
    )

    assert interrupted["__interrupt__"][0].value["type"] == "human_review"
    assert fake_session.committed is False

    result = await app.ainvoke(
        Command(resume=HumanMessage(content="同意")),
        config=config,
    )

    assert fake_session.committed is True
    assert FakeAssignedTaskDAO.created_data.task_name == "Task tracker"
    assert FakeAssignedTaskDAO.created_data.goal == "Create root task tracking"
    assert result["human_review_result"] is None
    assert "Task tracker" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_message_task_resumes_assign_task_after_human_approval(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)
    monkeypatch.setattr(GraphNode, "store_message", lambda config, messages: None)

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

    class ApprovalClassifier:
        async def ainvoke(self, messages):
            return AIMessage(content="approve")

        def get_resp_content(self, response):
            return response.content

    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            return RecallResult()

    class ApprovalTask(MsgQueueTask):
        def __init__(self):
            super().__init__(
                message="幫我建立 task",
                agent_id="agent-1",
                session_id="session-message-approve",
            )
            self.chunks = []

        async def callback(self, chunk):
            self.chunks.append(chunk)
            if chunk.chunk_type == "interrupt":
                return "approval-msg-1"
            return None

    async def get_approval_classifier():
        return ApprovalClassifier()

    async def get_agent(agent_id, session_id):
        return agent

    async def get_agent_sandbox(agent_id, user_id):
        return object()

    monkeypatch.setattr(
        "backend.graph.interrupt_nodes.LLMSet.getRteModel",
        get_approval_classifier,
    )
    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )
    monkeypatch.setattr(
        "backend.queues.msg_queue_handle.Agent.get_agent",
        get_agent,
    )
    monkeypatch.setattr(
        "backend.queues.msg_queue_handle.get_agent_sandbox",
        get_agent_sandbox,
    )

    agent = Bulter(
        123,
        456,
        789,
        "user-1",
        "Alice",
        "agent-1",
        "session-message-approve",
        "bulter",
        "Bulter",
    )
    monkeypatch.setattr(
        Bulter,
        "_graph",
        butler_workflow.compile(checkpointer=InMemorySaver()),
    )
    agent.models = FakeModels(ToolCallingLLM())

    task = ApprovalTask()

    assert await handle_agent_message(task) is False
    assert task.wait_msg_id == "approval-msg-1"
    assert fake_session.committed is False
    assert any(chunk.chunk_type == "interrupt" for chunk in task.chunks)

    task.message = "同意"
    task.wait_msg_id = None
    task.change_task_state(TaskState.RESUME)

    assert await handle_agent_message(task) is True

    assert fake_session.committed is True
    assert FakeAssignedTaskDAO.created_data.task_name == "Task tracker"
    assert FakeAssignedTaskDAO.created_data.goal == "Create root task tracking"
    assert any(
        chunk.chunk_type == "content" and "Task tracker" in str(chunk.content)
        for chunk in task.chunks
    )


class FakeGraph:
    configs = []

    async def astream(self, payload, config, stream_mode):
        assert payload["messages"][0].content == "hello"
        assert config["configurable"]["thread_id"] == "session-1"
        self.configs.append(config)
        assert stream_mode == ["messages", "updates"]
        yield (AIMessageChunk(content="he"), {"node": "chat"})
        yield AIMessage(content="llo", additional_kwargs={"text_done": True})


class FakeToolCallGraph:
    async def astream(self, payload, config, stream_mode):
        yield AIMessage(
            content="我先檢查檔案。",
            tool_calls=[
                {
                    "name": "list_files",
                    "args": {"path": "/workspace"},
                    "id": "call-1",
                }
            ],
        )


class FakeChunkedToolCallGraph:
    async def astream(self, payload, config, stream_mode):
        yield AIMessageChunk(content="我先檢查檔案。")
        yield AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "list_files",
                    "args": '{"path":"/workspace"}',
                    "id": "call-1",
                    "index": 0,
                }
            ],
        )


class FakeNodeTransitionGraph:
    async def astream(self, payload, config, stream_mode):
        yield (AIMessageChunk(content="我先準備。"), {"langgraph_node": "chat"})
        yield (
            ToolMessage(content="tool output", tool_call_id="call-1"),
            {"langgraph_node": "tools"},
        )


class FakeInterruptGraph:
    async def astream(self, payload, config, stream_mode):
        approval_message = AIMessage(content="請確認任務。")
        yield (
            "messages",
            (
                AIMessage(
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
                ),
                {"langgraph_node": "chat"},
            ),
        )
        yield (
            "messages",
            (
                approval_message,
                {"langgraph_node": "pre_assign_task_node"},
            ),
        )
        yield (
            "updates",
            {
                "__interrupt__": (
                    Interrupt(
                        value={"type": "human_review", "message": approval_message}
                    ),
                )
            },
        )


class FakeAgent:
    user_db_id = 1
    user_name = "Alice"
    agent_db_id = 2
    session_db_id = 3
    agent_id = "agent-1"
    agent_type = "assistant"
    session_id = "session-1"
    models = object()
    sys_prompt = ""
    sender_agent_name = "user"
    sender_agent_id = None
    sender_agent_db_id = None
    sender_agent_session_db_id = None
    sender_agent_session_id = None
    sender_is_sub_agent = False
    recv_agent_name = "agent"
    recv_is_sub_agent = False
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
        "Alice",
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
        "Alice",
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
        "Alice",
        "agent-1",
        "session-1",
        "assistant",
        "Receiver",
        "agent-sender-1",
        "Sender",
        99,
        100,
        "sender-default",
        True,
        False,
    )

    assert agent.sender_agent_id == "agent-sender-1"
    assert agent.sender_agent_db_id == 99
    assert agent.sender_agent_session_db_id == 100
    assert agent.sender_agent_session_id == "sender-default"
    assert agent.sender_is_sub_agent is True
    assert agent.recv_is_sub_agent is False
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
    graph.configs.clear()
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
    assert graph.configs[0]["configurable"]["user_name"] == "Alice"
    assert graph.configs[0]["configurable"]["agent_db_id"] == 2
    assert graph.configs[0]["configurable"]["agent_type"] == "assistant"
    assert graph.configs[0]["configurable"]["sender_agent_id"] == ""
    assert graph.configs[0]["configurable"]["sender_agent_db_id"] is None
    assert graph.configs[0]["configurable"]["sender_agent_session_db_id"] is None
    assert graph.configs[0]["configurable"]["sender_agent_session_id"] is None
    assert graph.configs[0]["configurable"]["sender_is_sub_agent"] is False
    assert graph.configs[0]["configurable"]["recv_is_sub_agent"] is False


@pytest.mark.asyncio
async def test_agent_proc_send_uses_public_sender_agent_id(monkeypatch):
    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            return RecallResult()

    class FakeSenderAgent(FakeAgent):
        sender_agent_id = "agent-sender-1"
        sender_agent_db_id = 99
        sender_agent_session_db_id = 100
        sender_agent_session_id = "sender-default"
        sender_agent_name = "Sender"
        sender_type = "agent"
        conversation_kind = "agent_to_agent"

    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    graph = FakeGraph()
    graph.configs.clear()
    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeSenderAgent(),
            message="hello",
            think_mode=False,
            metadata={},
            sandbox=None,
            graph=graph,
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == ["content", "content", "text_end"]
    assert graph.configs[0]["configurable"]["sender_agent_id"] == "agent-sender-1"
    assert graph.configs[0]["configurable"]["sender_agent_db_id"] == 99


@pytest.mark.asyncio
async def test_agent_proc_send_marks_complete_ai_message_with_tool_calls_as_text_end(monkeypatch):
    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            return RecallResult()

    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeAgent(),
            message="hello",
            think_mode=False,
            metadata={"source": "test"},
            sandbox=FakeSandbox(),
            graph=FakeToolCallGraph(),
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == ["tool", "content", "text_end"]
    assert chunks[0].content == "list_files"
    assert chunks[1].content == "我先檢查檔案。"


@pytest.mark.asyncio
async def test_agent_proc_send_flushes_text_before_chunked_tool_call(monkeypatch):
    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            return RecallResult()

    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeAgent(),
            message="hello",
            think_mode=False,
            metadata={"source": "test"},
            sandbox=FakeSandbox(),
            graph=FakeChunkedToolCallGraph(),
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == ["content", "text_end", "tool"]
    assert chunks[0].content == "我先檢查檔案。"
    assert chunks[2].content == "list_files"


@pytest.mark.asyncio
async def test_agent_proc_send_flushes_text_when_graph_node_changes(monkeypatch):
    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            return RecallResult()

    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeAgent(),
            message="hello",
            think_mode=False,
            metadata={"source": "test"},
            sandbox=FakeSandbox(),
            graph=FakeNodeTransitionGraph(),
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == [
        "content",
        "text_end",
        "tool_result",
    ]
    assert chunks[0].content == "我先準備。"


@pytest.mark.asyncio
async def test_agent_proc_send_streams_langgraph_interrupt_update(monkeypatch):
    class FakeMemoryManager:
        async def recall(self, *, agent_id, session_key, user_text):
            return RecallResult()

    monkeypatch.setattr(
        "backend.agent.agent.MemoryManager.instance",
        lambda: FakeMemoryManager(),
    )

    chunks = [
        chunk
        async for chunk in Agent.proc_send(
            agent=FakeAgent(),
            message="hello",
            think_mode=False,
            metadata={"source": "test"},
            sandbox=FakeSandbox(),
            graph=FakeInterruptGraph(),
        )
    ]

    assert [chunk.chunk_type for chunk in chunks] == [
        "tool",
        "text_end",
        "interrupt",
    ]
    assert chunks[0].content == "assign_task"
    assert chunks[1].content is None
    assert chunks[2].data == {"type": "human_review", "message": "請確認任務。"}


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
async def test_tool_node_returns_tool_message_when_tool_raises():
    @tool
    async def failing_tool() -> str:
        """Always fail."""
        raise RuntimeError("boom")

    graph = StateGraph(MessageState)
    graph.add_node("tools", GraphNode.build_tool_node([failing_tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    app = graph.compile()

    result = await app.ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "failing_tool", "args": {}, "id": "call-1"}],
                )
            ]
        }
    )

    message = result["messages"][-1]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call-1"
    assert message.content == t("graph.agent.tool_error") % "boom"


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


@pytest.mark.asyncio
async def test_chat_node_clears_brainstormer_content_when_tool_calling():
    class ToolLLM:
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="呢段追問正文不應由 chat content 輸出。",
                tool_calls=[
                    {
                        "name": "ask_user_question",
                        "args": {
                            "question": "請確認資料來源。",
                            "description": "要決定 seed 名單來源。",
                            "choose": ["日本100名城", "自訂匯入"],
                        },
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
        agent_type="brainstormer",
    )

    result = await chat_node({"messages": [HumanMessage(content="hello")]}, config)
    message = result["messages"][0]

    assert isinstance(message, AIMessage)
    assert message.content == ""
    assert message.additional_kwargs["text_done"] is True
    assert message.tool_calls[0]["name"] == "ask_user_question"
