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

    async def read_file(self, request: SandboxRequest, path: str, encoding: str) -> str:
        handle = await self.acquire(request)
        try:
            return await self.backend.read_file(handle, path, encoding)
        finally:
            await self.release(handle)

    async def write_file(self, request: SandboxRequest, path: str, content: str, encoding: str) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.write_file(handle, path, content, encoding)
        finally:
            await self.release(handle)

    async def edit_file(
        self,
        request: SandboxRequest,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        encoding: str,
    ) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.edit_file(handle, path, old_string, new_string, replace_all, encoding)
        finally:
            await self.release(handle)

    async def apply_patch(self, request: SandboxRequest, patch: str, strip: int) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.apply_patch(handle, patch, strip)
        finally:
            await self.release(handle)

    async def grep_files(
        self,
        request: SandboxRequest,
        pattern: str,
        path: str,
        recursive: bool,
        ignore_case: bool,
        include: str,
        max_results: int,
    ) -> list[str]:
        handle = await self.acquire(request)
        try:
            return await self.backend.grep_files(handle, pattern, path, recursive, ignore_case, include, max_results)
        finally:
            await self.release(handle)

    async def find_files(self, request: SandboxRequest, pattern: str, path: str, max_results: int) -> list[str]:
        handle = await self.acquire(request)
        try:
            return await self.backend.find_files(handle, pattern, path, max_results)
        finally:
            await self.release(handle)

    async def list_dir(self, request: SandboxRequest, path: str, show_hidden: bool) -> dict:
        handle = await self.acquire(request)
        try:
            return await self.backend.list_dir(handle, path, show_hidden)
        finally:
            await self.release(handle)
