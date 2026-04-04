from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sandbox.backends.remote_provisioner import RemoteProvisionerBackend
from sandbox.models import SandboxRequest
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
