from __future__ import annotations

import logging

import httpx

from sandbox.backends.base import SandboxBackend
from sandbox.logging import current_operation_id
from sandbox.models import SandboxHandle, SandboxRequest


logger = logging.getLogger(__name__)


class RemoteProvisionerBackend(SandboxBackend):
    def __init__(self, base_url: str, client: object | None = None, api_token: str = "", endpoint_client: object | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(base_url=self.base_url)
        self.api_token = api_token
        self.endpoint_client = endpoint_client

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
        handle = self._to_handle(response.json())
        logger.info("sandbox.remote.discover sandbox_id=%s endpoint=%s", request.sandbox_id, handle.endpoint)
        return handle

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
        handle = self._to_handle(response.json())
        logger.info("sandbox.remote.create sandbox_id=%s endpoint=%s", request.sandbox_id, handle.endpoint)
        return handle

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
        logger.info("sandbox.remote.destroy sandbox_id=%s endpoint=%s", handle.sandbox_id, handle.endpoint)
        await self._request("DELETE", f"/api/sandboxes/{handle.sandbox_id}")

    async def _endpoint_request(self, method: str, url: str, json: dict | None = None, token: str = "", sandbox_id: str = ""):
        headers = {"X-Sandbox-Token": token} if token else {}
        operation_id = current_operation_id()
        if operation_id:
            headers["X-Sandbox-Request-Id"] = operation_id
        if sandbox_id:
            headers["X-Sandbox-Id"] = sandbox_id
        if self.endpoint_client is not None:
            response = self.endpoint_client.request(method, url, json=json, headers=headers)
            if hasattr(response, "status_code"):
                return response
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, json=json, headers=headers)

    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int) -> str:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/exec", {"command": command, "cwd": cwd, "timeout": timeout}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()["stdout"]

    async def start_process(self, handle: SandboxHandle, command: str, cwd: str) -> dict:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/processes", {"command": command, "cwd": cwd}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()

    async def get_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        response = await self._endpoint_request("GET", f"{handle.endpoint}/v1/processes/{process_handle}", token=handle.metadata.get("sandbox_token", ""), sandbox_id=handle.sandbox_id)
        response.raise_for_status()
        return response.json()

    async def kill_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        response = await self._endpoint_request("DELETE", f"{handle.endpoint}/v1/processes/{process_handle}", token=handle.metadata.get("sandbox_token", ""), sandbox_id=handle.sandbox_id)
        response.raise_for_status()
        return response.json()

    async def read_file(self, handle: SandboxHandle, path: str, encoding: str) -> str:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/read", {"path": path, "encoding": encoding}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()["content"]

    async def write_file(self, handle: SandboxHandle, path: str, content: str, encoding: str) -> dict:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/write", {"path": path, "content": content, "encoding": encoding}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()

    async def edit_file(self, handle: SandboxHandle, path: str, old_string: str, new_string: str, replace_all: bool, encoding: str) -> dict:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/edit", {"path": path, "old_string": old_string, "new_string": new_string, "replace_all": replace_all, "encoding": encoding}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()

    async def apply_patch(self, handle: SandboxHandle, patch: str, strip: int) -> dict:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/apply-patch", {"patch": patch, "strip": strip}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()

    async def grep_files(self, handle: SandboxHandle, pattern: str, path: str, recursive: bool, ignore_case: bool, include: str, max_results: int) -> list[str]:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/grep", {"pattern": pattern, "path": path, "recursive": recursive, "ignore_case": ignore_case, "include": include, "max_results": max_results}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()["matches"]

    async def find_files(self, handle: SandboxHandle, pattern: str, path: str, max_results: int) -> list[str]:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/find", {"pattern": pattern, "path": path, "max_results": max_results}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()["matches"]

    async def list_dir(self, handle: SandboxHandle, path: str, show_hidden: bool) -> dict:
        response = await self._endpoint_request("POST", f"{handle.endpoint}/v1/files/list", {"path": path, "show_hidden": show_hidden}, handle.metadata.get("sandbox_token", ""), handle.sandbox_id)
        response.raise_for_status()
        return response.json()
