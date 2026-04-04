from __future__ import annotations

import asyncio
import os
import uuid


class ProcessManager:
    def __init__(self, max_output_bytes: int = 65536) -> None:
        self.max_output_bytes = max_output_bytes
        self.processes: dict[str, asyncio.subprocess.Process] = {}

    def _validate_cwd(self, cwd: str) -> None:
        if cwd != "." and cwd != "/workspace" and not cwd.startswith("/workspace/"):
            raise ValueError("cwd must stay within /workspace")

    def _truncate(self, value: str) -> str:
        encoded = value.encode()
        if len(encoded) <= self.max_output_bytes:
            return value
        return encoded[: self.max_output_bytes].decode(errors="ignore")

    def _runtime_cwd(self, cwd: str) -> str | None:
        if cwd == ".":
            return None
        if os.path.isdir(cwd):
            return cwd
        return None

    async def exec(self, command: str, cwd: str, timeout: int) -> dict:
        self._validate_cwd(cwd)
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._runtime_cwd(cwd),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            raise
        return {
            "stdout": self._truncate(stdout.decode(errors="replace")),
            "stderr": self._truncate(stderr.decode(errors="replace")),
            "exit_code": process.returncode,
        }

    async def start_process(self, command: str, cwd: str) -> dict:
        self._validate_cwd(cwd)
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._runtime_cwd(cwd),
        )
        handle = uuid.uuid4().hex
        self.processes[handle] = process
        return {"handle": handle, "pid": process.pid, "status": "running"}

    async def get_process(self, handle: str) -> dict:
        if handle not in self.processes:
            raise KeyError(handle)
        process = self.processes[handle]
        status = "running" if process.returncode is None else "exited"
        return {"handle": handle, "pid": process.pid, "status": status, "exit_code": process.returncode}

    async def kill_process(self, handle: str) -> dict:
        if handle not in self.processes:
            raise KeyError(handle)
        process = self.processes[handle]
        if process.returncode is None:
            process.kill()
            await process.wait()
            status = "killed"
        else:
            status = "exited"
        return {"handle": handle, "pid": process.pid, "status": status, "exit_code": process.returncode}
