from __future__ import annotations

import pytest

from sandbox.config import SandboxSettings, load_sandbox_settings
from sandbox.models import SandboxMount, SandboxRequest


def test_load_sandbox_settings_requires_provider_backend(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROVIDER", raising=False)
    monkeypatch.delenv("SANDBOX_BACKEND", raising=False)

    with pytest.raises(RuntimeError, match="SANDBOX_PROVIDER"):
        load_sandbox_settings()


def test_load_sandbox_settings_success(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "aio")
    monkeypatch.setenv("SANDBOX_BACKEND", "local_docker")
    monkeypatch.setenv("SANDBOX_DEFAULT_PROFILE", "default")
    monkeypatch.setenv("SANDBOX_IDLE_TIMEOUT_SECONDS", "1800")

    settings = load_sandbox_settings()

    assert settings == SandboxSettings(
        provider="aio",
        backend="local_docker",
        default_profile="default",
        idle_timeout_seconds=1800,
    )


def test_sandbox_request_id_is_deterministic():
    request = SandboxRequest(
        owner_id="user-1",
        scope="session",
        scope_key="thread-1",
        profile="default",
        network_mode="default",
        mounts=(SandboxMount(name="workspace", source="/tmp/a", target="/workspace", read_only=False),),
    )

    assert request.sandbox_id == request.model_copy().sandbox_id


def test_sandbox_request_id_changes_with_profile():
    request_a = SandboxRequest(
        owner_id="user-1",
        scope="session",
        scope_key="thread-1",
        profile="default",
        network_mode="default",
    )
    request_b = SandboxRequest(
        owner_id="user-1",
        scope="session",
        scope_key="thread-1",
        profile="networked",
        network_mode="default",
    )

    assert request_a.sandbox_id != request_b.sandbox_id
