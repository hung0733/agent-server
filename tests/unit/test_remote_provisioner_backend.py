from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sandbox.backends.remote_provisioner import RemoteProvisionerBackend
from sandbox.models import SandboxRequest
from sandbox_agent.app import create_app
from sandbox_provisioner.app import build_provisioner_app


@pytest.mark.asyncio
async def test_remote_backend_create_is_idempotent():
    app = build_provisioner_app()
    client = TestClient(app)
    backend = RemoteProvisionerBackend(base_url="http://testserver", client=client, api_token="secret")
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    first = await backend.create(request)
    second = await backend.discover(request)

    assert first.sandbox_id == second.sandbox_id


@pytest.mark.asyncio
async def test_remote_backend_reads_file_through_sandbox_endpoint(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "remote.txt").write_text("remote-data")
    app = build_provisioner_app(api_token="secret")
    client = TestClient(app)
    sandbox_client = TestClient(create_app(api_token="token", workspace_root=str(workspace)))
    backend = RemoteProvisionerBackend(base_url="http://testserver", client=client, api_token="secret", endpoint_client=sandbox_client)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    handle = await backend.create(request)
    handle.endpoint = ""
    handle.metadata["sandbox_token"] = "token"

    result = await backend.read_file(handle, "remote.txt", "utf-8")

    assert result == "remote-data"
