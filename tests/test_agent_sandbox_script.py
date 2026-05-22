from __future__ import annotations

import pytest

from scripts import test_agent_sandbox as smoke_script


class FakeSandbox:
    instances = []
    fail_step = None

    def __init__(self, user_id, timeout_minutes):
        self.user_id = user_id
        self.timeout_minutes = timeout_minutes
        self.calls = []
        FakeSandbox.instances.append(self)

    async def _record(self, name, result):
        self.calls.append(name)
        if FakeSandbox.fail_step == name:
            raise RuntimeError(f"failed {name}")
        return result

    async def create(self):
        return await self._record("create", {"sandbox_id": "sandbox-1"})

    async def get_info(self):
        return await self._record("get_info", {"info": {"status": {"state": "RUNNING"}}})

    async def run_command(self, command):
        if command == smoke_script.SMOKE_COMMAND:
            return await self._record("run_command", {"result": "sandbox-ok"})
        return await self._record("run_command_after_resume", {"result": smoke_script.SMOKE_FILE_CONTENT})

    async def write_file(self, path, content):
        assert path == smoke_script.SMOKE_FILE_PATH
        assert content == smoke_script.SMOKE_FILE_CONTENT
        return await self._record("write_file", {"path": path})

    async def read_file(self, path):
        assert path == smoke_script.SMOKE_FILE_PATH
        return await self._record("read_file", {"content": smoke_script.SMOKE_FILE_CONTENT})

    async def list_files(self, path, pattern):
        assert path == "/workspace"
        assert pattern == "smoke-test.txt"
        return await self._record("list_files", {"files": [{"path": smoke_script.SMOKE_FILE_PATH}]})

    async def renew(self, timeout_minutes):
        assert timeout_minutes == 10
        return await self._record("renew", {"result": {"renewed": 600}})

    async def pause(self):
        return await self._record("pause", {"result": {"paused": True}})

    async def resume(self):
        return await self._record("resume", {"sandbox_id": "sandbox-1"})

    async def delete_file(self, path):
        assert path == smoke_script.SMOKE_FILE_PATH
        return await self._record("delete_file", {"path": path})

    async def list_sandboxes(self):
        return await self._record("list_sandboxes", {"sandboxes": [{"id": "sandbox-1"}]})

    async def kill(self):
        self.calls.append("kill")
        return {"sandbox_id": "sandbox-1", "killed": True}


@pytest.fixture(autouse=True)
def fake_sandbox(monkeypatch):
    FakeSandbox.instances = []
    FakeSandbox.fail_step = None
    monkeypatch.setattr(smoke_script, "AgentSandbox", FakeSandbox)


@pytest.mark.asyncio
async def test_run_smoke_test_calls_all_sandbox_methods_in_order():
    exit_code = await smoke_script.run_smoke_test("user_123")

    assert exit_code == 0
    sandbox = FakeSandbox.instances[0]
    assert sandbox.user_id == "user_123"
    assert sandbox.timeout_minutes == 10
    assert sandbox.calls == [
        "create",
        "get_info",
        "run_command",
        "write_file",
        "read_file",
        "list_files",
        "renew",
        "pause",
        "resume",
        "run_command_after_resume",
        "delete_file",
        "list_sandboxes",
        "kill",
        "kill",
    ]


@pytest.mark.asyncio
async def test_run_smoke_test_kills_sandbox_when_step_fails():
    FakeSandbox.fail_step = "write_file"

    exit_code = await smoke_script.run_smoke_test("user_123")

    assert exit_code == 1
    assert FakeSandbox.instances[0].calls == [
        "create",
        "get_info",
        "run_command",
        "write_file",
        "kill",
    ]
