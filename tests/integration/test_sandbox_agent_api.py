from __future__ import annotations

from pathlib import Path

import logging

from fastapi.testclient import TestClient

from sandbox_agent.app import create_app


def test_sandbox_agent_health_and_exec():
    client = TestClient(create_app(api_token="secret"))

    health = client.get("/health")
    result = client.post(
        "/v1/exec",
        headers={"X-Sandbox-Token": "secret"},
        json={"command": "printf ok", "cwd": "/workspace", "timeout": 5},
    )

    assert health.status_code == 200
    assert result.status_code == 200
    assert result.json()["stdout"] == "ok"


def test_sandbox_agent_rejects_invalid_handle_and_timeout():
    client = TestClient(create_app(api_token="secret"))

    missing = client.get("/v1/processes/missing", headers={"X-Sandbox-Token": "secret"})
    timed_out = client.post(
        "/v1/exec",
        headers={"X-Sandbox-Token": "secret"},
        json={"command": "sleep 1", "cwd": "/workspace", "timeout": 0},
    )

    assert missing.status_code == 404
    assert timed_out.status_code == 408


def test_sandbox_agent_file_endpoints(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(api_token="secret", workspace_root=str(workspace)))

    write_result = client.post(
        "/v1/files/write",
        headers={"X-Sandbox-Token": "secret"},
        json={"path": "notes/agent.txt", "content": "hello sandbox", "encoding": "utf-8"},
    )
    read_result = client.post(
        "/v1/files/read",
        headers={"X-Sandbox-Token": "secret"},
        json={"path": "notes/agent.txt", "encoding": "utf-8"},
    )
    grep_result = client.post(
        "/v1/files/grep",
        headers={"X-Sandbox-Token": "secret"},
        json={"pattern": "sandbox", "path": "notes", "recursive": True, "include": "*.txt", "max_results": 10},
    )
    list_result = client.post(
        "/v1/files/list",
        headers={"X-Sandbox-Token": "secret"},
        json={"path": "notes", "show_hidden": False},
    )

    assert write_result.status_code == 200
    assert read_result.json()["content"] == "hello sandbox"
    assert grep_result.json()["matches"] == ["/workspace/notes/agent.txt:1:hello sandbox"]
    assert list_result.json()["entries"][0]["name"] == "agent.txt"


def test_sandbox_agent_accepts_virtual_workspace_paths_and_rejects_patch_escape(tmp_path):
    workspace = tmp_path / "workspace"
    virtual_file = workspace / "mnt/data/workspace/project/app.txt"
    virtual_file.parent.mkdir(parents=True)
    virtual_file.write_text("virtual")
    client = TestClient(create_app(api_token="secret", workspace_root=str(workspace)))

    read_result = client.post(
        "/v1/files/read",
        headers={"X-Sandbox-Token": "secret"},
        json={"path": "/mnt/data/workspace/project/app.txt", "encoding": "utf-8"},
    )
    patch_result = client.post(
        "/v1/files/apply-patch",
        headers={"X-Sandbox-Token": "secret"},
        json={"patch": "--- ../../etc/passwd\n+++ ../../etc/passwd\n@@\n-root\n+blocked\n", "strip": 0},
    )

    assert read_result.status_code == 200
    assert read_result.json()["content"] == "virtual"
    assert patch_result.status_code == 400


def test_sandbox_agent_logs_request_ids(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(api_token="secret", workspace_root=str(workspace)))

    response = client.post(
        "/v1/files/write",
        headers={"X-Sandbox-Token": "secret", "X-Sandbox-Request-Id": "req-1", "X-Sandbox-Id": "sandbox-1"},
        json={"path": "notes/agent.txt", "content": "hello sandbox", "encoding": "utf-8"},
    )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records]
    assert any("sandbox.request.start request_id=req-1 sandbox_id=sandbox-1 method=POST path=/v1/files/write" in message for message in messages)
    assert any("sandbox.file.write request_id=req-1 sandbox_id=sandbox-1 path=notes/agent.txt" in message for message in messages)
