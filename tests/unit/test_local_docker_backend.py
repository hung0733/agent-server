from __future__ import annotations

from pathlib import Path

import pytest

from sandbox.backends.local_docker import LocalDockerBackend
from sandbox.models import SandboxRequest


@pytest.mark.asyncio
async def test_container_name_is_deterministic(tmp_path):
    backend = LocalDockerBackend(base_url="http://127.0.0.1", host_workspace_root=tmp_path)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    assert backend._container_name(request) == backend._container_name(request)


def test_workspace_host_path_uses_owner_directory(tmp_path):
    backend = LocalDockerBackend(base_url="http://127.0.0.1", host_workspace_root=tmp_path)

    assert backend.workspace_host_path("user-1") == (tmp_path / "user-1").resolve()
