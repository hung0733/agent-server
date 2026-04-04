from __future__ import annotations

from pathlib import Path

import httpx

from sandbox.backends.base import SandboxBackend
from sandbox.models import SandboxHandle, SandboxRequest


class LocalDockerBackend(SandboxBackend):
    def __init__(
        self,
        base_url: str,
        host_workspace_root: str | Path,
        sandbox_token: str = "local-token",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.host_workspace_root = Path(host_workspace_root).resolve()
        self.sandbox_token = sandbox_token
        self.client = client or httpx.AsyncClient()
        self._handles: dict[str, SandboxHandle] = {}

    def workspace_host_path(self, owner_id: str) -> Path:
        return (self.host_workspace_root / owner_id).resolve()

    def _container_name(self, request: SandboxRequest) -> str:
        return f"agent-sandbox-{request.sandbox_id}"

    async def discover(self, request: SandboxRequest) -> SandboxHandle | None:
        return self._handles.get(request.sandbox_id)

    async def create(self, request: SandboxRequest) -> SandboxHandle:
        handle = SandboxHandle(
            sandbox_id=request.sandbox_id,
            owner_id=request.owner_id,
            scope=request.scope,
            scope_key=request.scope_key,
            profile=request.profile,
            endpoint=self.base_url,
            backend_type="local_docker",
            workspace_host_path=str(self.workspace_host_path(request.owner_id)),
            workspace_container_path="/workspace",
            metadata={"container_name": self._container_name(request), "sandbox_token": self.sandbox_token},
        )
        self._handles[request.sandbox_id] = handle
        return handle

    async def destroy(self, handle: SandboxHandle) -> None:
        self._handles.pop(handle.sandbox_id, None)

    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int) -> str:
        response = await self.client.post(
            f"{handle.endpoint}/v1/exec",
            headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", self.sandbox_token)},
            json={"command": command, "cwd": cwd, "timeout": timeout},
        )
        response.raise_for_status()
        return response.json()["stdout"]

    async def start_process(self, handle: SandboxHandle, command: str, cwd: str) -> dict:
        response = await self.client.post(
            f"{handle.endpoint}/v1/processes",
            headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", self.sandbox_token)},
            json={"command": command, "cwd": cwd},
        )
        response.raise_for_status()
        return response.json()

    async def get_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        response = await self.client.get(
            f"{handle.endpoint}/v1/processes/{process_handle}",
            headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", self.sandbox_token)},
        )
        response.raise_for_status()
        return response.json()

    async def kill_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        response = await self.client.delete(
            f"{handle.endpoint}/v1/processes/{process_handle}",
            headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", self.sandbox_token)},
        )
        response.raise_for_status()
        return response.json()
