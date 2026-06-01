from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Annotated, TypedDict

import pytest

from backend.i18n import t
from backend.tools.system import assign_task
from langchain_core.messages import AIMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt import ToolRuntime


class FakeAsyncSession:
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

    async def create_initial_steps(self, *, task_db_id, assign_agent_id, step_ids):
        type(self).initial_steps_args = (task_db_id, assign_agent_id, step_ids)
        return [
            SimpleNamespace(
                step_id=step_ids[0],
                title=t("tools.system.assign_task.step.brainstorm.title"),
                status="pending",
            ),
            SimpleNamespace(
                step_id=step_ids[1],
                title=t("tools.system.assign_task.step.planning.title"),
                status="blocked",
            ),
            SimpleNamespace(
                step_id=step_ids[2],
                title=t("tools.system.assign_task.step.review.title"),
                status="blocked",
            ),
        ]


def _runtime() -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"user_db_id": 1, "agent_db_id": 2}},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )


def _runtime_with_db_ids() -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=None,
        config={
            "configurable": {
                "user_db_id": 123,
                "agent_db_id": 456,
            }
        },
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )


def _patch_assign_task_persistence(monkeypatch):
    fake_session = FakeAsyncSession()
    FakeAssignedTaskDAO.created_data = None
    FakeAssignedTaskDAO.initial_steps_args = None
    monkeypatch.setattr(
        "backend.tools.system.async_session_factory",
        lambda: fake_session,
    )
    monkeypatch.setattr(
        "backend.tools.system.AssignedTaskDAO",
        FakeAssignedTaskDAO,
    )
    return fake_session


def test_assign_task_schema_exposes_only_task_name_and_goal():
    schema = assign_task.args_schema.model_json_schema()

    assert assign_task.description == t("tools.system.assign_task.description")
    assert set(schema["properties"]) == {"task_name", "goal"}
    assert schema["required"] == ["task_name", "goal"]
    assert "runtime" not in schema["properties"]
    assert (
        schema["properties"]["task_name"]["description"]
        == t("tools.system.assign_task.task_name.description")
    )
    assert (
        schema["properties"]["goal"]["description"]
        == t("tools.system.assign_task.goal.description")
    )


@pytest.mark.asyncio
async def test_assign_task_rejects_blank_task_name():
    result = await assign_task.coroutine("   ", "建立網站", _runtime())

    assert result == {
        "accepted": False,
        "error": t("tools.system.assign_task.blank_task_name"),
    }


@pytest.mark.asyncio
async def test_assign_task_rejects_blank_goal():
    result = await assign_task.coroutine("打卡網站", "   ", _runtime())

    assert result == {
        "accepted": False,
        "error": t("tools.system.assign_task.blank_goal"),
    }


@pytest.mark.asyncio
async def test_assign_task_creates_root_task_and_initial_steps(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)

    result = await assign_task.coroutine(
        "Task tracker",
        "Create root task tracking",
        _runtime_with_db_ids(),
    )

    assert result["accepted"] is True
    assert result["task_id"].startswith("task_")
    assert result["task_name"] == "Task tracker"
    assert result["status"] == "brainstorm_pending"
    assert [step["title"] for step in result["steps"]] == [
        t("tools.system.assign_task.step.brainstorm.title"),
        t("tools.system.assign_task.step.planning.title"),
        t("tools.system.assign_task.step.review.title"),
    ]
    assert [step["status"] for step in result["steps"]] == [
        "pending",
        "blocked",
        "blocked",
    ]
    assert fake_session.committed is True

    created_data = FakeAssignedTaskDAO.created_data
    assert created_data.user_id == 123
    assert created_data.responsible_agent_id == 456

    task_db_id, assign_agent_id, step_ids = FakeAssignedTaskDAO.initial_steps_args
    assert task_db_id == 99
    assert assign_agent_id == 456
    assert len(step_ids) == 3
    assert all(step_id.startswith("step_") for step_id in step_ids)


@pytest.mark.asyncio
async def test_tool_node_injects_runtime_config_for_assign_task(monkeypatch):
    fake_session = _patch_assign_task_persistence(monkeypatch)

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    graph = StateGraph(State)
    graph.add_node("tools", ToolNode([assign_task]))
    graph.add_edge(START, "tools")
    app = graph.compile()

    result = await app.ainvoke(
        {
            "messages": [
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
                )
            ]
        },
        config={
            "configurable": {
                "user_db_id": 123,
                "agent_db_id": 456,
            }
        },
    )

    output = json.loads(result["messages"][-1].content)
    assert output["accepted"] is True
    assert output["task_name"] == "Task tracker"
    assert fake_session.committed is True
    assert FakeAssignedTaskDAO.created_data.user_id == 123
    assert FakeAssignedTaskDAO.created_data.responsible_agent_id == 456
