from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from sandbox.backends.base import SandboxBackend
from sandbox.models import SandboxHandle, SandboxRequest


CommandRunner = Callable[[list[str]], Awaitable[str]]


async def _default_command_runner(command: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace") or stdout.decode(errors="replace"))
    return stdout.decode(errors="replace").strip()


class LocalDockerBackend(SandboxBackend):
    def __init__(
        self,
        base_url: str,
        host_workspace_root: str | Path,
        sandbox_token: str = "local-token",
        client: httpx.AsyncClient | None = None,
        image: str = "agent-sandbox:latest",
        docker_bin: str = "docker",
        command_runner: CommandRunner | None = None,
        health_client: object | None = None,
        startup_timeout_seconds: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.host_workspace_root = Path(host_workspace_root).resolve()
        self.sandbox_token = sandbox_token
        self.client = client or httpx.AsyncClient()
        self.image = image
        self.docker_bin = docker_bin
        self.command_runner = command_runner or _default_command_runner
        self.health_client = health_client or self.client
        self.startup_timeout_seconds = startup_timeout_seconds
        self._handles: dict[str, SandboxHandle] = {}

    def workspace_host_path(self, owner_id: str) -> Path:
        if not owner_id or "/" in owner_id or "\\" in owner_id or ".." in owner_id:
            raise ValueError("owner_id contains invalid path characters")
        resolved = (self.host_workspace_root / owner_id).resolve()
        try:
            resolved.relative_to(self.host_workspace_root)
        except ValueError as exc:
            raise ValueError("owner_id resolves outside workspace root") from exc
        return resolved

    def _container_name(self, request: SandboxRequest) -> str:
        return f"agent-sandbox-{request.sandbox_id}"

    async def _inspect_container(self, container_name: str) -> dict | None:
        try:
            output = await self.command_runner(
                [self.docker_bin, "inspect", container_name, "--format", "{{json .}}"]
            )
        except RuntimeError:
            return None
        return json.loads(output)

    def _endpoint_from_inspect(self, inspect_payload: dict) -> str:
        port_bindings = inspect_payload["NetworkSettings"]["Ports"].get("8080/tcp") or []
        if not port_bindings:
            raise RuntimeError("Sandbox container has no published 8080/tcp port")
        binding = port_bindings[0]
        host_ip = binding.get("HostIp") or "127.0.0.1"
        if host_ip == "0.0.0.0":
            host_ip = "127.0.0.1"
        return f"http://{host_ip}:{binding['HostPort']}"

    async def _wait_until_healthy(self, endpoint: str) -> None:
        attempts = max(1, self.startup_timeout_seconds)
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = await self.health_client.get(f"{endpoint}/health")
                response.raise_for_status()
                if response.json().get("status") == "ok":
                    return
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(1)
        raise RuntimeError(f"Sandbox health check failed: {last_error}")

    async def discover(self, request: SandboxRequest) -> SandboxHandle | None:
        if request.sandbox_id in self._handles:
            return self._handles[request.sandbox_id]

        container_name = self._container_name(request)
        inspect_payload = await self._inspect_container(container_name)
        if inspect_payload is None:
            return None

        handle = SandboxHandle(
            sandbox_id=request.sandbox_id,
            owner_id=request.owner_id,
            scope=request.scope,
            scope_key=request.scope_key,
            profile=request.profile,
            endpoint=self._endpoint_from_inspect(inspect_payload),
            backend_type="local_docker",
            workspace_host_path=str(self.workspace_host_path(request.owner_id)),
            workspace_container_path="/workspace",
            metadata={
                "container_id": inspect_payload.get("Id", ""),
                "container_name": container_name,
                "sandbox_token": self.sandbox_token,
            },
        )
        self._handles[request.sandbox_id] = handle
        return handle

    async def create(self, request: SandboxRequest) -> SandboxHandle:
        existing = await self.discover(request)
        if existing is not None:
            return existing

        workspace_path = self.workspace_host_path(request.owner_id)
        workspace_path.mkdir(parents=True, exist_ok=True)
        container_name = self._container_name(request)
        run_command = [
            self.docker_bin,
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-P",
            "-e",
            f"SANDBOX_API_TOKEN={self.sandbox_token}",
            "-v",
            f"{workspace_path}:/workspace",
        ]
        if request.network_mode:
            run_command.extend(["--network", request.network_mode])
        for mount in request.mounts:
            suffix = ":ro" if mount.read_only else ""
            run_command.extend(["-v", f"{mount.source}:{mount.target}{suffix}"])
        run_command.append(self.image)
        container_id = await self.command_runner(run_command)
        try:
            inspect_payload = await self._inspect_container(container_name)
            if inspect_payload is None:
                raise RuntimeError("Sandbox container was created but cannot be inspected")
            endpoint = self._endpoint_from_inspect(inspect_payload)
            await self._wait_until_healthy(endpoint)
        except Exception:
            await self.command_runner([self.docker_bin, "rm", "-f", container_id.strip()])
            raise

        handle = SandboxHandle(
            sandbox_id=request.sandbox_id,
            owner_id=request.owner_id,
            scope=request.scope,
            scope_key=request.scope_key,
            profile=request.profile,
            endpoint=endpoint,
            backend_type="local_docker",
            workspace_host_path=str(workspace_path),
            workspace_container_path="/workspace",
            metadata={
                "container_id": container_id.strip(),
                "container_name": container_name,
                "sandbox_token": self.sandbox_token,
            },
        )
        self._handles[request.sandbox_id] = handle
        return handle

    async def destroy(self, handle: SandboxHandle) -> None:
        container_id = handle.metadata.get("container_id") or handle.metadata.get("container_name")
        if container_id:
            await self.command_runner([self.docker_bin, "rm", "-f", container_id])
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
