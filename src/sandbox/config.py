from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxSettings:
    provider: str
    backend: str
    default_profile: str
    idle_timeout_seconds: int


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def load_sandbox_settings() -> SandboxSettings:
    return SandboxSettings(
        provider=_required_env("SANDBOX_PROVIDER"),
        backend=_required_env("SANDBOX_BACKEND"),
        default_profile=_required_env("SANDBOX_DEFAULT_PROFILE"),
        idle_timeout_seconds=int(_required_env("SANDBOX_IDLE_TIMEOUT_SECONDS")),
    )
