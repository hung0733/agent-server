from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from sandbox.backends.local_docker import LocalDockerBackend
from sandbox.backends.remote_provisioner import RemoteProvisionerBackend
from sandbox.provider import SandboxProvider


@lru_cache(maxsize=1)
def _build_provider() -> SandboxProvider:
    backend = os.environ.get("SANDBOX_BACKEND")
    if backend == "remote_provisioner":
        base_url = os.environ.get("SANDBOX_PROVISIONER_URL")
        token = os.environ.get("SANDBOX_PROVISIONER_TOKEN")
        if not base_url:
            raise RuntimeError("SANDBOX_PROVISIONER_URL is required")
        if not token:
            raise RuntimeError("SANDBOX_PROVISIONER_TOKEN is required")
        return SandboxProvider(RemoteProvisionerBackend(base_url=base_url, api_token=token))

    if backend not in {None, "", "local_docker"}:
        raise RuntimeError(f"unsupported SANDBOX_BACKEND: {backend}")

    api_base = os.environ.get("SANDBOX_AGENT_BASE_URL")
    host_root = os.environ.get("AGENT_HOME_DIR")
    if not api_base:
        raise RuntimeError("SANDBOX_AGENT_BASE_URL is required")
    if not host_root:
        raise RuntimeError("AGENT_HOME_DIR is required")
    token = os.environ.get("SANDBOX_API_TOKEN")
    if not token:
        raise RuntimeError("SANDBOX_API_TOKEN is required")
    return SandboxProvider(
        LocalDockerBackend(
            base_url=api_base,
            host_workspace_root=Path(host_root),
            sandbox_token=token,
        )
    )


def get_sandbox_provider(_config: dict | None = None) -> SandboxProvider:
    return _build_provider()
