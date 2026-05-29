from __future__ import annotations

import logging
import os
import posixpath
import shlex
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from backend.i18n import t


logger = logging.getLogger(__name__)

WORKSPACE_MOUNT_PATH = "/workspace"
DEFAULT_SANDBOX_IMAGE = "ubuntu:22.04"
_UNCHANGED = object()


class AgentSandbox:
    def __init__(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        *,
        timeout_minutes: int | None = 30,
        sandbox: Any | None = None,
    ) -> None:
        self.user_id = user_id
        self.agent_id = agent_id
        self.timeout_minutes = timeout_minutes
        self._sandbox = sandbox
        self.working_directory = WORKSPACE_MOUNT_PATH

    async def __aenter__(self) -> AgentSandbox:
        await self.create()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.kill()

    @property
    def sandbox_id(self) -> str | None:
        return _get_attr(self._sandbox, "id")

    async def create(
        self,
        user_id: str | None = None,
        timeout_minutes: int | None | object = _UNCHANGED,
    ) -> dict[str, Any]:
        load_dotenv()
        if user_id is not None:
            self.user_id = user_id
        if timeout_minutes is not _UNCHANGED:
            self.timeout_minutes = timeout_minutes  # type: ignore[assignment]

        valid_user_id = _validate_user_id(self.user_id)
        home_path = _agent_home_path(valid_user_id)
        home_path.mkdir(parents=True, exist_ok=True)

        sdk = _load_opensandbox_sdk()
        config = _connection_config(sdk.ConnectionConfig)
        volume = sdk.Volume(
            name="agent-workspace",
            host=sdk.Host(path=str(home_path)),
            mountPath=WORKSPACE_MOUNT_PATH,
            readOnly=False,
        )
        metadata = {"agent_server_user_id": valid_user_id}
        if self.agent_id is not None:
            metadata["agent_server_agent_id"] = self.agent_id

        kwargs: dict[str, Any] = {
            "image": os.getenv("SANDBOX_IMAGE", DEFAULT_SANDBOX_IMAGE),
            "connection_config": config,
            "volumes": [volume],
            "metadata": metadata,
        }
        if self.timeout_minutes is not None:
            kwargs["timeout"] = timedelta(minutes=self.timeout_minutes)

        self._sandbox = await sdk.Sandbox.create(**kwargs)
        logger.info(t("sandbox.agent.created"), self.sandbox_id, valid_user_id)
        return {
            "sandbox_id": self.sandbox_id,
            "user_id": valid_user_id,
            "host_path": str(home_path),
            "mount_path": WORKSPACE_MOUNT_PATH,
            "image": kwargs["image"],
        }

    async def run_command(self, command: str) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        sdk = _load_opensandbox_sdk()
        result = await sandbox.commands.run(
            command,
            opts=sdk.RunCommandOpts(working_directory=self.working_directory),
        )
        return {"sandbox_id": self.sandbox_id, "result": _json_safe(result)}

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        sdk = _load_opensandbox_sdk()
        resolved_path = self._resolve_path(path)
        await sandbox.files.write_files(
            [
                sdk.WriteEntry(
                    path=resolved_path,
                    data=content,
                    mode=0o644,
                )
            ]
        )
        return {"sandbox_id": self.sandbox_id, "path": resolved_path}

    async def read_file(self, path: str) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        resolved_path = self._resolve_path(path)
        content = await sandbox.files.read_file(resolved_path)
        return {
            "sandbox_id": self.sandbox_id,
            "path": resolved_path,
            "content": content,
        }

    async def list_files(
        self,
        path: str = ".",
        pattern: str = "*",
    ) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        sdk = _load_opensandbox_sdk()
        resolved_path = self._resolve_path(path)
        files = await sandbox.files.search(
            sdk.SearchEntry(path=resolved_path, pattern=pattern)
        )
        return {
            "sandbox_id": self.sandbox_id,
            "path": resolved_path,
            "files": _json_safe(files),
        }

    async def delete_file(self, path: str) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        resolved_path = self._resolve_path(path)
        await sandbox.files.delete_files([resolved_path])
        return {"sandbox_id": self.sandbox_id, "path": resolved_path}

    async def copy(self, src: str, dest: str) -> dict[str, Any]:
        resolved_src = self._resolve_path(src)
        resolved_dest = self._resolve_path(dest)
        result = await self.run_command(
            f"cp -R -- {shlex.quote(resolved_src)} {shlex.quote(resolved_dest)}"
        )
        return {
            "sandbox_id": self.sandbox_id,
            "src": resolved_src,
            "dest": resolved_dest,
            "result": result["result"],
        }

    async def rename(self, src: str, dest: str) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        sdk = _load_opensandbox_sdk()
        resolved_src = self._resolve_path(src)
        resolved_dest = self._resolve_path(dest)
        await sandbox.files.move_files(
            [sdk.MoveEntry(src=resolved_src, dest=resolved_dest)]
        )
        return {
            "sandbox_id": self.sandbox_id,
            "src": resolved_src,
            "dest": resolved_dest,
        }

    async def pwd(self) -> dict[str, Any]:
        self._require_sandbox()
        return {"sandbox_id": self.sandbox_id, "path": self.working_directory}

    async def cd(self, path: str) -> dict[str, Any]:
        resolved_path = self._resolve_path(path)
        result = await self.run_command(f"cd -- {shlex.quote(resolved_path)} && pwd")
        stdout = _result_stdout_text(result["result"])
        if not stdout:
            raise RuntimeError(t("sandbox.agent.cd_failed") % resolved_path)
        self.working_directory = stdout.strip().splitlines()[-1]
        return {"sandbox_id": self.sandbox_id, "path": self.working_directory}

    async def renew(self, timeout_minutes: int) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        result = await sandbox.renew(timedelta(minutes=timeout_minutes))
        return {"sandbox_id": self.sandbox_id, "result": _json_safe(result)}

    async def pause(self) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        result = await sandbox.pause()
        return {"sandbox_id": self.sandbox_id, "result": _json_safe(result)}

    async def resume(self) -> dict[str, Any]:
        sandbox_id = self.sandbox_id
        if not sandbox_id:
            raise RuntimeError(t("sandbox.agent.not_created"))
        sdk = _load_opensandbox_sdk()
        self._sandbox = await sdk.Sandbox.resume(
            sandbox_id=sandbox_id,
            connection_config=_connection_config(sdk.ConnectionConfig),
        )
        return {"sandbox_id": self.sandbox_id}

    async def get_info(self) -> dict[str, Any]:
        sandbox = self._require_sandbox()
        info = await sandbox.get_info()
        return {"sandbox_id": self.sandbox_id, "info": _json_safe(info)}

    async def kill(self) -> dict[str, Any]:
        if self._sandbox is None:
            return {"sandbox_id": None, "killed": False}

        sandbox_id = self.sandbox_id
        await self._sandbox.kill()
        self._sandbox = None
        logger.info(t("sandbox.agent.killed"), sandbox_id)
        return {"sandbox_id": sandbox_id, "killed": True}

    async def list_sandboxes(self) -> dict[str, Any]:
        sdk = _load_opensandbox_sdk()
        async with await sdk.SandboxManager.create(
            connection_config=_connection_config(sdk.ConnectionConfig)
        ) as manager:
            infos = await manager.list_sandbox_infos(sdk.SandboxFilter())
        return {"sandboxes": _json_safe(infos)}

    def _require_sandbox(self) -> Any:
        if self._sandbox is None:
            raise RuntimeError(t("sandbox.agent.not_created"))
        return self._sandbox

    def _resolve_path(self, path: str) -> str:
        if path.startswith("/"):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(self.working_directory, path))


class _OpenSandboxSdk:
    def __init__(
        self,
        *,
        Sandbox: Any,
        SandboxManager: Any,
        ConnectionConfig: Any,
        Host: Any,
        Volume: Any,
        SandboxFilter: Any,
        WriteEntry: Any,
        SearchEntry: Any,
        MoveEntry: Any,
        RunCommandOpts: Any,
    ) -> None:
        self.Sandbox = Sandbox
        self.SandboxManager = SandboxManager
        self.ConnectionConfig = ConnectionConfig
        self.Host = Host
        self.Volume = Volume
        self.SandboxFilter = SandboxFilter
        self.WriteEntry = WriteEntry
        self.SearchEntry = SearchEntry
        self.MoveEntry = MoveEntry
        self.RunCommandOpts = RunCommandOpts


def _load_opensandbox_sdk() -> _OpenSandboxSdk:
    try:
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
        from opensandbox.manager import SandboxManager
        from opensandbox.models.execd import RunCommandOpts
        from opensandbox.models.filesystem import MoveEntry, SearchEntry, WriteEntry
        from opensandbox.models.sandboxes import Host, SandboxFilter, Volume
    except ImportError as exc:
        raise RuntimeError(t("sandbox.agent.sdk_missing")) from exc

    return _OpenSandboxSdk(
        Sandbox=Sandbox,
        SandboxManager=SandboxManager,
        ConnectionConfig=ConnectionConfig,
        Host=Host,
        Volume=Volume,
        SandboxFilter=SandboxFilter,
        WriteEntry=WriteEntry,
        SearchEntry=SearchEntry,
        MoveEntry=MoveEntry,
        RunCommandOpts=RunCommandOpts,
    )


def _connection_config(connection_config_cls: Any) -> Any:
    endpoint = os.getenv("SANDBOX_ENDPOINT")
    api_key = os.getenv("SANDBOX_API_KEY")
    if not endpoint or not api_key:
        raise RuntimeError(t("sandbox.agent.missing_config"))

    parsed = urlparse(endpoint)
    if parsed.scheme:
        protocol = parsed.scheme
        domain = parsed.netloc
    else:
        protocol = "http"
        domain = endpoint.rstrip("/")

    return connection_config_cls(
        domain=domain,
        api_key=api_key,
        protocol=protocol,
        use_server_proxy=_env_bool("SANDBOX_USE_SERVER_PROXY", default=False),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _agent_home_path(user_id: str) -> Path:
    home_dir = os.getenv("AGENT_HOME_DIR")
    if not home_dir:
        raise RuntimeError(t("sandbox.agent.missing_config"))
    return Path(home_dir) / user_id


def _validate_user_id(user_id: str | None) -> str:
    if not user_id or "/" in user_id or "\\" in user_id or ".." in user_id:
        raise ValueError(t("sandbox.agent.invalid_user_id"))
    return user_id


def _get_attr(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump())
    if hasattr(value, "__dict__"):
        return {
            key: _json_safe(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


def _result_stdout_text(result: Any) -> str:
    logs = (
        result.get("logs")
        if isinstance(result, dict)
        else getattr(result, "logs", None)
    )
    if not logs:
        return ""

    stdout = (
        logs.get("stdout")
        if isinstance(logs, dict)
        else getattr(logs, "stdout", None)
    )
    if isinstance(stdout, str):
        return stdout
    if isinstance(stdout, list):
        return "\n".join(str(line) for line in stdout)
    return ""
