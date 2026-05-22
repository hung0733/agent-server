from __future__ import annotations

import logging
from typing import Annotated, TypedDict

from backend.i18n import t
from backend.tools.system import assign_task
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


def test_assign_task_schema_exposes_only_task_json():
    schema = assign_task.args_schema.model_json_schema()

    assert assign_task.description == t("tools.system.assign_task.description")
    assert set(schema["properties"]) == {"task_json"}
    assert schema["required"] == ["task_json"]
    assert "runtime" not in schema["properties"]
    assert (
        schema["properties"]["task_json"]["description"]
        == t("tools.system.assign_task.task_json.description")
    )


def test_assign_task_logs_json_payload(caplog):
    task_json = '{"task":"demo"}'
    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )

    with caplog.at_level(logging.INFO, logger="backend.tools.system"):
        result = assign_task.func(task_json, runtime)

    assert result == {
        "accepted": True,
        "length": len(task_json),
        "tool_call_id": "call-1",
    }
    assert task_json in caplog.text
    assert "call-1" in caplog.text


def test_assign_task_tool_node_injects_runtime():
    class State(TypedDict):
        messages: Annotated[list, add_messages]

    graph = StateGraph(State)
    graph.add_node("tools", ToolNode([assign_task]))
    graph.add_edge(START, "tools")
    app = graph.compile()

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

    result = app.invoke({"messages": [message]})

    assert '"tool_call_id": "call-1"' in result["messages"][-1].content
