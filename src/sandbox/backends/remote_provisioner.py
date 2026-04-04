from __future__ import annotations

import httpx

from sandbox.backends.base import SandboxBackend
from sandbox.models import SandboxHandle, SandboxRequest


class RemoteProvisionerBackend(SandboxBackend):
    def __init__(self, base_url: str, client: object | None = None, api_token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(base_url=self.base_url)
        self.api_token = api_token

    async def _request(self, method: str, path: str, json: dict | None = None):
        headers = {"X-Provisioner-Token": self.api_token} if self.api_token else None
        if hasattr(self.client, "request"):
            response = self.client.request(method, path, json=json, headers=headers)
            if hasattr(response, "status_code"):
                return response
        return await self.client.request(method, path, json=json, headers=headers)

    async def discover(self, request: SandboxRequest) -> SandboxHandle | None:
        response = await self._request("GET", f"/api/sandboxes/{request.sandbox_id}")
        if response.status_code == 404:
            return None
        return self._to_handle(response.json())

    async def create(self, request: SandboxRequest) -> SandboxHandle:
        response = await self._request(
            "POST",
            "/api/sandboxes",
            json={
                "sandbox_id": request.sandbox_id,
                "owner_id": request.owner_id,
                "scope": request.scope,
                "scope_key": request.scope_key,
                "profile": request.profile,
                "network_mode": request.network_mode,
                "mounts": [mount.__dict__ for mount in request.mounts],
            },
        )
        return self._to_handle(response.json())

    def _to_handle(self, payload: dict) -> SandboxHandle:
        return SandboxHandle(
            sandbox_id=payload["sandbox_id"],
            owner_id=payload["owner_id"],
            scope=payload["scope"],
            scope_key=payload["scope_key"],
            profile=payload["profile"],
            endpoint=payload["endpoint"],
            backend_type=payload["backend_type"],
            workspace_host_path=payload["workspace_host_path"],
            workspace_container_path=payload["workspace_container_path"],
            metadata=payload.get("metadata", {}),
        )

    async def destroy(self, handle: SandboxHandle) -> None:
        await self._request("DELETE", f"/api/sandboxes/{handle.sandbox_id}")

    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{handle.endpoint}/v1/exec",
                headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", "")},
                json={"command": command, "cwd": cwd, "timeout": timeout},
            )
            response.raise_for_status()
            return response.json()["stdout"]

    async def start_process(self, handle: SandboxHandle, command: str, cwd: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{handle.endpoint}/v1/processes",
                headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", "")},
                json={"command": command, "cwd": cwd},
            )
            response.raise_for_status()
            return response.json()

    async def get_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{handle.endpoint}/v1/processes/{process_handle}",
                headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", "")},
            )
            response.raise_for_status()
            return response.json()

    async def kill_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{handle.endpoint}/v1/processes/{process_handle}",
                headers={"X-Sandbox-Token": handle.metadata.get("sandbox_token", "")},
            )
            response.raise_for_status()
            return response.json()
