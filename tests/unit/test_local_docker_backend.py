from __future__ import annotations

from pathlib import Path

import pytest

from sandbox.backends.local_docker import LocalDockerBackend
from sandbox.models import SandboxMount, SandboxRequest


@pytest.mark.asyncio
async def test_container_name_is_deterministic(tmp_path):
    backend = LocalDockerBackend(base_url="http://127.0.0.1", host_workspace_root=tmp_path)
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    assert backend._container_name(request) == backend._container_name(request)


def test_workspace_host_path_uses_owner_directory(tmp_path):
    backend = LocalDockerBackend(base_url="http://127.0.0.1", host_workspace_root=tmp_path)

    assert backend.workspace_host_path("user-1") == (tmp_path / "user-1").resolve()


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeHealthClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url: str):
        self.calls.append(url)
        if not self.responses:
            return FakeResponse(200, {"status": "ok"})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_discover_reads_existing_container_metadata(tmp_path):
    commands = []

    async def fake_runner(command):
        commands.append(command)
        return '{"Id":"cid-1","Name":"agent-sandbox-91cac3","NetworkSettings":{"Ports":{"8080/tcp":[{"HostIp":"127.0.0.1","HostPort":"38080"}]}}}'

    backend = LocalDockerBackend(
        base_url="http://127.0.0.1",
        host_workspace_root=tmp_path,
        command_runner=fake_runner,
    )
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    handle = await backend.discover(request)

    assert handle is not None
    assert handle.endpoint == "http://127.0.0.1:38080"
    assert commands[0][:2] == ["docker", "inspect"]


@pytest.mark.asyncio
async def test_create_runs_docker_and_waits_for_health(tmp_path):
    commands = []
    inspect_calls = 0

    async def fake_runner(command):
        nonlocal inspect_calls
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            inspect_calls += 1
            if inspect_calls == 1:
                raise RuntimeError("No such container")
            return '{"Id":"cid-1","Name":"agent-sandbox-91cac3","NetworkSettings":{"Ports":{"8080/tcp":[{"HostIp":"127.0.0.1","HostPort":"38080"}]}}}'
        return "cid-1"

    backend = LocalDockerBackend(
        base_url="http://127.0.0.1",
        host_workspace_root=tmp_path,
        image="agent-sandbox:test",
        sandbox_token="secret",
        command_runner=fake_runner,
        health_client=FakeHealthClient([FakeResponse(200, {"status": "ok"})]),
    )
    request = SandboxRequest(
        owner_id="user-1",
        scope="session",
        scope_key="thread-1",
        profile="default",
        network_mode="none",
        mounts=(SandboxMount(name="skills", source="/srv/skills", target="/mnt/skills", read_only=True),),
    )

    handle = await backend.create(request)

    assert handle.metadata["container_id"] == "cid-1"
    assert handle.endpoint == "http://127.0.0.1:38080"
    docker_run = next(command for command in commands if command[:2] == ["docker", "run"])
    assert "--network" in docker_run
    assert "none" in docker_run
    assert "/srv/skills:/mnt/skills:ro" in docker_run


@pytest.mark.asyncio
async def test_destroy_removes_container_by_id(tmp_path):
    commands = []

    async def fake_runner(command):
        commands.append(command)
        return "removed"

    backend = LocalDockerBackend(
        base_url="http://127.0.0.1",
        host_workspace_root=tmp_path,
        command_runner=fake_runner,
    )

    from sandbox.models import SandboxHandle

    handle = SandboxHandle(
        sandbox_id="sandbox-1",
        owner_id="user-1",
        scope="session",
        scope_key="thread-1",
        profile="default",
        endpoint="http://127.0.0.1:38080",
        backend_type="local_docker",
        workspace_host_path=str(tmp_path / "user-1"),
        workspace_container_path="/workspace",
        metadata={"container_id": "cid-1", "container_name": "agent-sandbox-sandbox-1", "sandbox_token": "secret"},
    )

    await backend.destroy(handle)

    assert commands == [["docker", "rm", "-f", "cid-1"]]


@pytest.mark.asyncio
async def test_create_cleans_up_container_when_health_fails(tmp_path):
    commands = []
    inspect_calls = 0

    async def fake_runner(command):
        nonlocal inspect_calls
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            inspect_calls += 1
            if inspect_calls == 1:
                raise RuntimeError("No such container")
            return '{"Id":"cid-1","Name":"agent-sandbox-91cac3","NetworkSettings":{"Ports":{"8080/tcp":[{"HostIp":"127.0.0.1","HostPort":"38080"}]}}}'
        return "cid-1"

    backend = LocalDockerBackend(
        base_url="http://127.0.0.1",
        host_workspace_root=tmp_path,
        command_runner=fake_runner,
        health_client=FakeHealthClient([FakeResponse(503, {"status": "booting"})]),
        startup_timeout_seconds=1,
    )
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    with pytest.raises(RuntimeError, match="health check"):
        await backend.create(request)

    assert commands[-1] == ["docker", "rm", "-f", "cid-1"]


@pytest.mark.asyncio
async def test_discover_normalizes_wildcard_host_ip(tmp_path):
    async def fake_runner(command):
        return '{"Id":"cid-1","Name":"agent-sandbox-91cac3","NetworkSettings":{"Ports":{"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"38080"}]}}}'

    backend = LocalDockerBackend(
        base_url="http://127.0.0.1",
        host_workspace_root=tmp_path,
        command_runner=fake_runner,
    )
    request = SandboxRequest(owner_id="user-1", scope="session", scope_key="thread-1", profile="default")

    handle = await backend.discover(request)

    assert handle.endpoint == "http://127.0.0.1:38080"


def test_workspace_host_path_rejects_path_traversal(tmp_path):
    backend = LocalDockerBackend(base_url="http://127.0.0.1", host_workspace_root=tmp_path)

    with pytest.raises(ValueError, match="owner_id"):
        backend.workspace_host_path("../escape")
