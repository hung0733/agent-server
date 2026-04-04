from __future__ import annotations

from sandbox.backends.base import SandboxBackend
from sandbox.models import SandboxHandle, SandboxRequest
from sandbox.registry import SandboxRegistry


def _touch(handle: SandboxHandle) -> SandboxHandle:
    handle.metadata["last_used_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return handle


class SandboxProvider:
    def __init__(self, backend: SandboxBackend) -> None:
        self.backend = backend
        self.registry = SandboxRegistry()

    async def acquire(self, request: SandboxRequest) -> SandboxHandle:
        if request.sandbox_id in self.registry.active:
            return _touch(self.registry.active[request.sandbox_id])
        if request.sandbox_id in self.registry.idle:
            handle = self.registry.idle.pop(request.sandbox_id)
            self.registry.active[request.sandbox_id] = _touch(handle)
            return handle

        handle = await self.backend.discover(request)
        if handle is None:
            handle = await self.backend.create(request)
        self.registry.active[request.sandbox_id] = _touch(handle)
        return handle

    async def release(self, handle: SandboxHandle) -> None:
        self.registry.active.pop(handle.sandbox_id, None)
        self.registry.idle[handle.sandbox_id] = handle

    async def destroy(self, handle: SandboxHandle) -> None:
        await self.backend.destroy(handle)
        self.registry.active.pop(handle.sandbox_id, None)
        self.registry.idle.pop(handle.sandbox_id, None)

    async def exec(self, request: SandboxRequest, command: str, cwd: str, timeout: int) -> str:
        handle = await self.acquire(request)
        try:
            return await self.backend.exec(handle, command, cwd, timeout)
        finally:
            await self.release(handle)

    async def start_process(self, request: SandboxRequest, command: str, cwd: str) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.start_process(handle, command, cwd)
        finally:
            await self.release(handle)

    async def get_process(self, request: SandboxRequest, process_handle: str) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.get_process(handle, process_handle)
        finally:
            await self.release(handle)

    async def kill_process(self, request: SandboxRequest, process_handle: str) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.kill_process(handle, process_handle)
        finally:
            await self.release(handle)
