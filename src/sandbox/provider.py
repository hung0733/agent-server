from __future__ import annotations

import logging

from sandbox.backends.base import SandboxBackend
from sandbox.logging import operation_context
from sandbox.models import SandboxHandle, SandboxRequest
from sandbox.registry import SandboxRegistry


logger = logging.getLogger(__name__)


def _touch(handle: SandboxHandle) -> SandboxHandle:
    handle.metadata["last_used_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return handle


class SandboxProvider:
    def __init__(self, backend: SandboxBackend) -> None:
        self.backend = backend
        self.registry = SandboxRegistry()

    async def acquire(self, request: SandboxRequest) -> SandboxHandle:
        if request.sandbox_id in self.registry.active:
            logger.info(
                "sandbox.acquire action=active_reuse sandbox_id=%s owner_id=%s scope=%s scope_key=%s",
                request.sandbox_id,
                request.owner_id,
                request.scope,
                request.scope_key,
            )
            return _touch(self.registry.active[request.sandbox_id])
        if request.sandbox_id in self.registry.idle:
            handle = self.registry.idle.pop(request.sandbox_id)
            self.registry.active[request.sandbox_id] = _touch(handle)
            logger.info(
                "sandbox.acquire action=idle_reuse sandbox_id=%s owner_id=%s scope=%s scope_key=%s",
                request.sandbox_id,
                request.owner_id,
                request.scope,
                request.scope_key,
            )
            return handle

        handle = await self.backend.discover(request)
        if handle is None:
            handle = await self.backend.create(request)
            logger.info(
                "sandbox.acquire action=create sandbox_id=%s owner_id=%s scope=%s scope_key=%s backend=%s",
                request.sandbox_id,
                request.owner_id,
                request.scope,
                request.scope_key,
                handle.backend_type,
            )
        else:
            logger.info(
                "sandbox.acquire action=discover sandbox_id=%s owner_id=%s scope=%s scope_key=%s backend=%s",
                request.sandbox_id,
                request.owner_id,
                request.scope,
                request.scope_key,
                handle.backend_type,
            )
        self.registry.active[request.sandbox_id] = _touch(handle)
        return handle

    async def release(self, handle: SandboxHandle) -> None:
        self.registry.active.pop(handle.sandbox_id, None)
        self.registry.idle[handle.sandbox_id] = handle
        logger.info("sandbox.release sandbox_id=%s backend=%s", handle.sandbox_id, handle.backend_type)

    async def destroy(self, handle: SandboxHandle) -> None:
        await self.backend.destroy(handle)
        self.registry.active.pop(handle.sandbox_id, None)
        self.registry.idle.pop(handle.sandbox_id, None)
        logger.info("sandbox.destroy sandbox_id=%s backend=%s", handle.sandbox_id, handle.backend_type)

    async def exec(self, request: SandboxRequest, command: str, cwd: str, timeout: int) -> str:
        async with operation_context() as operation_id:
            logger.info("sandbox.exec.start sandbox_id=%s operation_id=%s cwd=%s timeout=%s", request.sandbox_id, operation_id, cwd, timeout)
            handle = await self.acquire(request)
            try:
                return await self.backend.exec(handle, command, cwd, timeout)
            finally:
                await self.release(handle)

    async def start_process(self, request: SandboxRequest, command: str, cwd: str) -> dict:
        async with operation_context() as operation_id:
            logger.info("sandbox.process.start sandbox_id=%s operation_id=%s cwd=%s", request.sandbox_id, operation_id, cwd)
            handle = await self.acquire(request)
            try:
                return await self.backend.start_process(handle, command, cwd)
            finally:
                await self.release(handle)

    async def get_process(self, request: SandboxRequest, process_handle: str) -> dict:
        async with operation_context() as operation_id:
            logger.info("sandbox.process.status sandbox_id=%s operation_id=%s handle=%s", request.sandbox_id, operation_id, process_handle)
            handle = await self.acquire(request)
            try:
                return await self.backend.get_process(handle, process_handle)
            finally:
                await self.release(handle)

    async def kill_process(self, request: SandboxRequest, process_handle: str) -> dict:
        async with operation_context() as operation_id:
            logger.info("sandbox.process.kill sandbox_id=%s operation_id=%s handle=%s", request.sandbox_id, operation_id, process_handle)
            handle = await self.acquire(request)
            try:
                return await self.backend.kill_process(handle, process_handle)
            finally:
                await self.release(handle)

    async def read_file(self, request: SandboxRequest, path: str, encoding: str) -> str:
        async with operation_context() as operation_id:
            logger.info("sandbox.file.read sandbox_id=%s operation_id=%s path=%s", request.sandbox_id, operation_id, path)
            handle = await self.acquire(request)
            try:
                return await self.backend.read_file(handle, path, encoding)
            finally:
                await self.release(handle)

    async def write_file(self, request: SandboxRequest, path: str, content: str, encoding: str) -> dict:
        async with operation_context() as operation_id:
            logger.info("sandbox.file.write sandbox_id=%s operation_id=%s path=%s bytes=%s", request.sandbox_id, operation_id, path, len(content.encode(encoding)))
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
        async with operation_context() as operation_id:
            logger.info("sandbox.file.edit sandbox_id=%s operation_id=%s path=%s replace_all=%s", request.sandbox_id, operation_id, path, replace_all)
            handle = await self.acquire(request)
            try:
                return await self.backend.edit_file(handle, path, old_string, new_string, replace_all, encoding)
            finally:
                await self.release(handle)

    async def apply_patch(self, request: SandboxRequest, patch: str, strip: int) -> dict:
        async with operation_context() as operation_id:
            logger.info("sandbox.file.apply_patch sandbox_id=%s operation_id=%s patch_bytes=%s strip=%s", request.sandbox_id, operation_id, len(patch.encode()), strip)
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
        async with operation_context() as operation_id:
            logger.info("sandbox.file.grep sandbox_id=%s operation_id=%s path=%s pattern=%s", request.sandbox_id, operation_id, path, pattern)
            handle = await self.acquire(request)
            try:
                return await self.backend.grep_files(handle, pattern, path, recursive, ignore_case, include, max_results)
            finally:
                await self.release(handle)

    async def find_files(self, request: SandboxRequest, pattern: str, path: str, max_results: int) -> list[str]:
        async with operation_context() as operation_id:
            logger.info("sandbox.file.find sandbox_id=%s operation_id=%s path=%s pattern=%s", request.sandbox_id, operation_id, path, pattern)
            handle = await self.acquire(request)
            try:
                return await self.backend.find_files(handle, pattern, path, max_results)
            finally:
                await self.release(handle)

    async def list_dir(self, request: SandboxRequest, path: str, show_hidden: bool) -> dict:
        async with operation_context() as operation_id:
            logger.info("sandbox.file.list sandbox_id=%s operation_id=%s path=%s show_hidden=%s", request.sandbox_id, operation_id, path, show_hidden)
            handle = await self.acquire(request)
            try:
                return await self.backend.list_dir(handle, path, show_hidden)
            finally:
                await self.release(handle)
