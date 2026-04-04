from __future__ import annotations

from fastapi.testclient import TestClient

from sandbox_provisioner.app import build_provisioner_app


def test_provisioner_create_get_delete_roundtrip():
    client = TestClient(build_provisioner_app(api_token="secret"))
    payload = {
        "sandbox_id": "sandbox-1",
        "owner_id": "user-1",
        "scope": "session",
        "scope_key": "thread-1",
        "profile": "default",
        "network_mode": "default",
        "mounts": [],
    }

    headers = {"X-Provisioner-Token": "secret"}

    created = client.post("/api/sandboxes", json=payload, headers=headers)
    fetched = client.get("/api/sandboxes/sandbox-1", headers=headers)
    deleted = client.delete("/api/sandboxes/sandbox-1", headers=headers)

    assert created.status_code == 200
    assert fetched.status_code == 200
    assert deleted.status_code == 200


def test_provisioner_rejects_missing_token():
    client = TestClient(build_provisioner_app(api_token="secret"))

    response = client.get("/api/sandboxes/missing")

    assert response.status_code == 401
