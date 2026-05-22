from __future__ import annotations

import pytest
from langchain.tools import ToolRuntime

from backend.i18n import t
from backend.tools import sandbox as sandbox_tools


class FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.sandbox_id = "sandbox-1"

    async def run_command(self, command: str):
        self.calls.append(("run_command", command))
        return {"sandbox_id": "sandbox-1", "result": {"exit_code": 0}}

    async def write_file(self, path: str, content: str):
        self.calls.append(("write_file", path, content))
        return {"sandbox_id": "sandbox-1", "path": path}

    async def read_file(self, path: str):
        self.calls.append(("read_file", path))
        return {"sandbox_id": "sandbox-1", "path": path, "content": "hello"}

    async def list_files(self, path: str = ".", pattern: str = "*"):
        self.calls.append(("list_files", path, pattern))
        return {"sandbox_id": "sandbox-1", "path": path, "files": []}

    async def delete_file(self, path: str):
        self.calls.append(("delete_file", path))
        return {"sandbox_id": "sandbox-1", "path": path}

    async def copy(self, src: str, dest: str):
        self.calls.append(("copy", src, dest))
        return {"sandbox_id": "sandbox-1", "src": src, "dest": dest}

    async def rename(self, src: str, dest: str):
        self.calls.append(("rename", src, dest))
        return {"sandbox_id": "sandbox-1", "src": src, "dest": dest}

    async def pwd(self):
        self.calls.append(("pwd",))
        return {"sandbox_id": "sandbox-1", "path": "/workspace"}

    async def cd(self, path: str):
        self.calls.append(("cd", path))
        return {"sandbox_id": "sandbox-1", "path": path}


def test_run_command_schema_exposes_only_command():
    schema = sandbox_tools.run_command.args_schema.model_json_schema()

    assert sandbox_tools.run_command.description == t("tools.sandbox.run_command.description")
    assert set(schema["properties"]) == {"command"}
    assert schema["required"] == ["command"]
    assert (
        schema["properties"]["command"]["description"]
        == t("tools.sandbox.run_command.command.description")
    )


@pytest.mark.parametrize(
    ("tool", "fields", "required"),
    [
        (sandbox_tools.write_file, {"path", "content"}, ["path", "content"]),
        (sandbox_tools.read_file, {"path"}, ["path"]),
        (sandbox_tools.list_files, {"path", "pattern"}, []),
        (sandbox_tools.delete_file, {"path"}, ["path"]),
        (sandbox_tools.copy, {"src", "dest"}, ["src", "dest"]),
        (sandbox_tools.rename, {"src", "dest"}, ["src", "dest"]),
        (sandbox_tools.pwd, set(), []),
        (sandbox_tools.cd, {"path"}, ["path"]),
    ],
)
def test_sandbox_tool_schemas_expose_only_llm_arguments(tool, fields, required):
    schema = tool.args_schema.model_json_schema()

    assert set(schema.get("properties", {})) == fields
    assert schema.get("required", []) == required
    assert "runtime" not in schema.get("properties", {})


@pytest.mark.asyncio
async def test_run_command_uses_configured_sandbox():
    sandbox = FakeSandbox()
    runtime = ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"sandbox": sandbox}},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )

    result = await sandbox_tools.run_command.coroutine("echo ok", runtime)

    assert result == {"exit_code": 0}
    assert sandbox.calls == [("run_command", "echo ok")]


@pytest.mark.asyncio
async def test_file_tools_use_configured_sandbox():
    sandbox = FakeSandbox()
    runtime = ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"sandbox": sandbox}},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )

    assert await sandbox_tools.write_file.coroutine("a.txt", "hello", runtime) == {
        "sandbox_id": "sandbox-1",
        "path": "a.txt",
    }
    assert await sandbox_tools.read_file.coroutine("a.txt", runtime) == {
        "sandbox_id": "sandbox-1",
        "path": "a.txt",
        "content": "hello",
    }
    assert await sandbox_tools.list_files.coroutine(
        runtime=runtime,
        path=".",
        pattern="*.py",
    ) == {
        "sandbox_id": "sandbox-1",
        "path": ".",
        "files": [],
    }
    assert await sandbox_tools.delete_file.coroutine("a.txt", runtime) == {
        "sandbox_id": "sandbox-1",
        "path": "a.txt",
    }
    assert await sandbox_tools.copy.coroutine("a.txt", "b.txt", runtime) == {
        "sandbox_id": "sandbox-1",
        "src": "a.txt",
        "dest": "b.txt",
    }
    assert await sandbox_tools.rename.coroutine("b.txt", "c.txt", runtime) == {
        "sandbox_id": "sandbox-1",
        "src": "b.txt",
        "dest": "c.txt",
    }
    assert await sandbox_tools.pwd.coroutine(runtime.config) == {
        "sandbox_id": "sandbox-1",
        "path": "/workspace",
    }
    assert await sandbox_tools.cd.coroutine("src", runtime) == {
        "sandbox_id": "sandbox-1",
        "path": "src",
    }

    assert sandbox.calls == [
        ("write_file", "a.txt", "hello"),
        ("read_file", "a.txt"),
        ("list_files", ".", "*.py"),
        ("delete_file", "a.txt"),
        ("copy", "a.txt", "b.txt"),
        ("rename", "b.txt", "c.txt"),
        ("pwd",),
        ("cd", "src"),
    ]
