from __future__ import annotations

import logging

import pytest

from sandbox.backends.base import SandboxBackend
from sandbox.factory import _build_provider
from sandbox.models import SandboxHandle, SandboxRequest
from sandbox.provider import SandboxProvider


class LoggingBackend(SandboxBackend):
    def __init__(self) -> None:
        self.created = 0

    async def discover(self, request: SandboxRequest):
        return None

    async def create(self, request: SandboxRequest):
        self.created += 1
        return SandboxHandle(
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

    async def destroy(self, handle: SandboxHandle):
        return None

    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int):
        return "ok"

    async def start_process(self, handle: SandboxHandle, command: str, cwd: str):
        return {"handle": "p"}

    async def get_process(self, handle: SandboxHandle, process_handle: str):
        return {"handle": process_handle}

    async def kill_process(self, handle: SandboxHandle, process_handle: str):
        return {"handle": process_handle}

    async def read_file(self, handle: SandboxHandle, path: str, encoding: str):
        return "x"

    async def write_file(self, handle: SandboxHandle, path: str, content: str, encoding: str):
        return {"path": path}

    async def edit_file(self, handle: SandboxHandle, path: str, old_string: str, new_string: str, replace_all: bool, encoding: str):
        return {"path": path, "replacements": 1}

    async def apply_patch(self, handle: SandboxHandle, patch: str, strip: int):
        return {"stdout": "ok"}

    async def grep_files(self, handle: SandboxHandle, pattern: str, path: str, recursive: bool, ignore_case: bool, include: str, max_results: int):
        return []

    async def find_files(self, handle: SandboxHandle, pattern: str, path: str, max_results: int):
        return []

    async def list_dir(self, handle: SandboxHandle, path: str, show_hidden: bool):
        return {"path": path, "entries": []}


@pytest.mark.asyncio
async def test_provider_logs_create_and_release(caplog):
    caplog.set_level(logging.INFO)
    provider = SandboxProvider(LoggingBackend())
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    await provider.read_file(request, "a.txt", "utf-8")

    messages = [record.getMessage() for record in caplog.records]
    assert any("sandbox.acquire action=create" in message for message in messages)
    assert any("sandbox.release sandbox_id=" in message for message in messages)


def test_factory_rejects_unsupported_backend(monkeypatch):
    _build_provider.cache_clear()
    monkeypatch.setenv("SANDBOX_BACKEND", "local-docker")

    with pytest.raises(RuntimeError, match="unsupported"):
        _build_provider()
