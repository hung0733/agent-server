from __future__ import annotations

import asyncio
import json
import re
import subprocess
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

    def _normalize_cwd(self, cwd: str) -> str:
        if not cwd or cwd == ".":
            return "."
        if cwd.startswith("/workspace"):
            return cwd
        return f"/workspace/{cwd.lstrip('/')}"

    def _validate_glob(self, value: str) -> None:
        if value.startswith("/") or ".." in Path(value).parts:
            raise RuntimeError("glob escapes sandbox workspace")

    def _extract_patch_target_paths(self, patch: str) -> list[str]:
        targets: list[str] = []
        for line in patch.splitlines():
            if line.startswith(("--- ", "+++ ")):
                raw_path = line[4:].split("\t", 1)[0].strip()
                if raw_path and raw_path != "/dev/null":
                    targets.append(raw_path)
        return targets

    def _validate_patch_targets(self, handle: SandboxHandle, patch: str, strip: int) -> None:
        for raw_path in self._extract_patch_target_paths(patch):
            path_obj = Path(raw_path)
            if path_obj.is_absolute():
                self._resolve_file_path(handle, raw_path)
                continue
            parts = [part for part in path_obj.parts if part and part != path_obj.anchor]
            if strip > 0:
                parts = parts[strip:]
            normalized = "." if not parts else str(Path(*parts))
            self._resolve_file_path(handle, normalized)

    def _resolve_file_path(self, handle: SandboxHandle, path: str) -> Path:
        root = Path(handle.workspace_host_path).resolve()
        candidate = Path(path)
        if candidate.is_absolute():
            candidate = candidate.relative_to("/")
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("path escapes sandbox workspace") from exc
        return resolved

    def _display_path(self, handle: SandboxHandle, resolved: Path) -> str:
        root = Path(handle.workspace_host_path).resolve()
        return str(Path("/") / resolved.relative_to(root))

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

    async def read_file(self, handle: SandboxHandle, path: str, encoding: str) -> str:
        resolved = self._resolve_file_path(handle, path)
        return resolved.read_text(encoding=encoding)

    async def write_file(self, handle: SandboxHandle, path: str, content: str, encoding: str) -> dict:
        resolved = self._resolve_file_path(handle, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
        return {"path": self._display_path(handle, resolved)}

    async def edit_file(
        self,
        handle: SandboxHandle,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        encoding: str,
    ) -> dict:
        resolved = self._resolve_file_path(handle, path)
        original = resolved.read_text(encoding=encoding)
        if old_string not in original:
            return {"path": self._display_path(handle, resolved), "replacements": 0}
        if replace_all:
            updated = original.replace(old_string, new_string)
            count = original.count(old_string)
        else:
            updated = original.replace(old_string, new_string, 1)
            count = 1
        resolved.write_text(updated, encoding=encoding)
        return {"path": self._display_path(handle, resolved), "replacements": count}

    async def apply_patch(self, handle: SandboxHandle, patch: str, strip: int) -> dict:
        try:
            self._validate_patch_targets(handle, patch, strip)
        except RuntimeError as exc:
            raise RuntimeError("patch target escapes sandbox workspace") from exc
        proc = await asyncio.create_subprocess_exec(
            "patch",
            f"-p{strip}",
            "--batch",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=handle.workspace_host_path,
        )
        stdout, stderr = await proc.communicate(input=patch.encode())
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace") or stdout.decode(errors="replace"))
        return {"stdout": stdout.decode(errors="replace")}

    async def grep_files(
        self,
        handle: SandboxHandle,
        pattern: str,
        path: str,
        recursive: bool,
        ignore_case: bool,
        include: str,
        max_results: int,
    ) -> list[str]:
        root = self._resolve_file_path(handle, path)
        if include:
            self._validate_glob(include)
        flags = re.IGNORECASE if ignore_case else 0
        compiled = re.compile(pattern, flags)
        search_files = [root] if root.is_file() else list(root.glob(f"**/{include}" if include and recursive else (include or "**/*" if recursive else include or "*")))
        results: list[str] = []
        for file_path in search_files:
            if not file_path.is_file():
                continue
            text = file_path.read_text(errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    results.append(f"{self._display_path(handle, file_path)}:{lineno}:{line}")
                    if len(results) >= max_results:
                        return results
        return results

    async def find_files(self, handle: SandboxHandle, pattern: str, path: str, max_results: int) -> list[str]:
        root = self._resolve_file_path(handle, path)
        self._validate_glob(pattern)
        return [self._display_path(handle, p) for p in sorted(root.glob(pattern))[:max_results]]

    async def list_dir(self, handle: SandboxHandle, path: str, show_hidden: bool) -> dict:
        root = self._resolve_file_path(handle, path)
        entries = []
        for entry in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if not show_hidden and entry.name.startswith("."):
                continue
            entries.append({"name": entry.name, "is_file": entry.is_file(), "size": entry.stat().st_size if entry.is_file() else 0})
        return {"path": self._display_path(handle, root), "entries": entries}
