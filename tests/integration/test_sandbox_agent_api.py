from __future__ import annotations

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
