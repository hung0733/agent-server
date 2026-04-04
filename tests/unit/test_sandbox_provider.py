from __future__ import annotations

import pytest

from sandbox.backends.base import SandboxBackend
from sandbox.models import SandboxHandle, SandboxRequest
from sandbox.provider import SandboxProvider


class FakeBackend(SandboxBackend):
    def __init__(self) -> None:
        self.created = 0
        self.handles: dict[str, SandboxHandle] = {}

    async def discover(self, request: SandboxRequest) -> SandboxHandle | None:
        return self.handles.get(request.sandbox_id)

    async def create(self, request: SandboxRequest) -> SandboxHandle:
        self.created += 1
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

    async def destroy(self, handle: SandboxHandle) -> None:
        self.handles.pop(handle.sandbox_id, None)

    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int) -> str:
        return f"{handle.sandbox_id}:{command}:{cwd}:{timeout}"

    async def start_process(self, handle: SandboxHandle, command: str, cwd: str) -> dict:
        return {"handle": f"proc:{handle.sandbox_id}", "command": command, "cwd": cwd}

    async def get_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        return {"handle": process_handle, "status": "running"}

    async def kill_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        return {"handle": process_handle, "status": "killed"}


@pytest.mark.asyncio
async def test_provider_discovers_before_creating():
    backend = FakeBackend()
    provider = SandboxProvider(backend)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    await provider.acquire(request)
    await provider.acquire(request)

    assert backend.created == 1


@pytest.mark.asyncio
async def test_provider_release_marks_handle_idle():
    backend = FakeBackend()
    provider = SandboxProvider(backend)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")
    handle = await provider.acquire(request)

    await provider.release(handle)

    assert provider.registry.idle[handle.sandbox_id].sandbox_id == handle.sandbox_id


@pytest.mark.asyncio
async def test_provider_destroy_removes_handle():
    backend = FakeBackend()
    provider = SandboxProvider(backend)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")
    handle = await provider.acquire(request)

    await provider.destroy(handle)

    assert handle.sandbox_id not in provider.registry.active
    assert handle.sandbox_id not in backend.handles


@pytest.mark.asyncio
async def test_provider_exec_releases_handle_to_idle_pool():
    backend = FakeBackend()
    provider = SandboxProvider(backend)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    result = await provider.exec(request, "pwd", ".", 30)

    assert result.endswith(":pwd:.:30")
    assert request.sandbox_id not in provider.registry.active
    assert request.sandbox_id in provider.registry.idle
