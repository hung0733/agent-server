from __future__ import annotations

import pytest

from sandbox_agent.process_manager import ProcessManager


@pytest.mark.asyncio
async def test_exec_runs_command_and_returns_output():
    manager = ProcessManager(max_output_bytes=2048)

    result = await manager.exec(command="printf hello", cwd=".", timeout=5)

    assert result["exit_code"] == 0
    assert result["stdout"] == "hello"


@pytest.mark.asyncio
async def test_start_process_status_and_kill():
    manager = ProcessManager(max_output_bytes=2048)

    started = await manager.start_process(command="sleep 10", cwd=".")
    status = await manager.get_process(started["handle"])
    killed = await manager.kill_process(started["handle"])

    assert status["status"] in {"running", "exited"}
    assert killed["status"] in {"killed", "exited"}


@pytest.mark.asyncio
async def test_rejects_workspace_prefix_escape(tmp_path):
    outside = tmp_path / "workspace2"
    outside.mkdir()
    manager = ProcessManager(max_output_bytes=2048)

    with pytest.raises(ValueError, match="/workspace"):
        await manager.exec(command="pwd", cwd=str(outside), timeout=5)
