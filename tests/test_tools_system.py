from __future__ import annotations

import json
import logging
from typing import Annotated, TypedDict

from backend.i18n import t
from backend.tools.system import assign_task, validate_assign_task_payload
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
    task_json = '{"state":"request","agent":"Hephaestus","mission":"整打卡 web","extra":"demo"}'
    runtime = ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"assign_task_allowed_agent_names": ["Hephaestus"]}},
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


def test_assign_task_rejects_missing_required_fields():
    error = validate_assign_task_payload(
        '{"title":"日本百名城打卡網站開發","description":"建立 web"}',
        ["Hephaestus"],
    )

    assert error == {
        "error": t("tools.system.assign_task.missing_required_fields"),
        "missing_fields": ["state", "agent", "mission"],
    }


def test_assign_task_rejects_invalid_agent_name():
    error = validate_assign_task_payload(
        '{"state":"request","agent":"Unknown","mission":"整打卡 web"}',
        ["Hephaestus"],
    )

    assert error == {
        "error": t("tools.system.assign_task.invalid_agent"),
        "invalid_agent": "Unknown",
        "available_agents": ["Hephaestus"],
    }


def test_assign_task_rejects_empty_mission():
    error = validate_assign_task_payload(
        '{"state":"request","agent":"Hephaestus","mission":"   "}',
        ["Hephaestus"],
    )

    assert error == {
        "error": t("tools.system.assign_task.missing_required_fields"),
        "missing_fields": ["mission"],
    }


def test_assign_task_rejects_non_object_json():
    error = validate_assign_task_payload('["state","request"]', ["Hephaestus"])

    assert error == {"error": t("tools.system.assign_task.invalid_object")}


def test_assign_task_rejects_invalid_json():
    error = validate_assign_task_payload("{not-json", ["Hephaestus"])

    assert error == {"error": t("tools.system.assign_task.invalid_json")}


def test_assign_task_accepts_extra_fields_for_valid_payload():
    error = validate_assign_task_payload(
        json.dumps(
            {
                "state": "request",
                "agent": "Hephaestus",
                "mission": "整打卡 web",
                "description": "建立一個日本百名城打卡網站",
                "features": ["列表", "打卡"],
            },
            ensure_ascii=False,
        ),
        ["Hephaestus"],
    )

    assert error is None


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
                "args": {
                    "task_json": '{"state":"request","agent":"Hephaestus","mission":"整打卡 web"}'
                },
                "id": "call-1",
            }
        ],
    )

    result = app.invoke(
        {"messages": [message]},
        config={"configurable": {"assign_task_allowed_agent_names": ["Hephaestus"]}},
    )

    assert '"tool_call_id": "call-1"' in result["messages"][-1].content
