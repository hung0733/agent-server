from __future__ import annotations

import pytest

from sandbox.backends.base import SandboxBackend
from sandbox.models import SandboxHandle, SandboxRequest
from sandbox.provider import SandboxProvider


class LifecycleBackend(SandboxBackend):
    def __init__(self) -> None:
        self.handles = {}

    async def discover(self, request: SandboxRequest):
        return self.handles.get(request.sandbox_id)

    async def create(self, request: SandboxRequest):
        handle = SandboxHandle(
            sandbox_id=request.sandbox_id,
            owner_id=request.owner_id,
            scope=request.scope,
            scope_key=request.scope_key,
            profile=request.profile,
            endpoint="http://sandbox.local",
            backend_type="fake",
            workspace_host_path="/tmp/host",
            workspace_container_path="/workspace",
        )
        self.handles[request.sandbox_id] = handle
        return handle

    async def destroy(self, handle: SandboxHandle):
        self.handles.pop(handle.sandbox_id, None)

    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int):
        return command

    async def start_process(self, handle: SandboxHandle, command: str, cwd: str):
        return {"handle": "proc"}

    async def get_process(self, handle: SandboxHandle, process_handle: str):
        return {"handle": process_handle, "status": "running"}

    async def kill_process(self, handle: SandboxHandle, process_handle: str):
        return {"handle": process_handle, "status": "killed"}


@pytest.mark.asyncio
async def test_same_session_reuses_same_sandbox():
    provider = SandboxProvider(LifecycleBackend())
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    first = await provider.acquire(request)
    second = await provider.acquire(request)

    assert first.sandbox_id == second.sandbox_id
