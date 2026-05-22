from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.sandbox import agent_sandbox
from backend.sandbox.agent_sandbox import AgentSandbox, WORKSPACE_MOUNT_PATH


@dataclass
class FakeConnectionConfig:
    domain: str
    api_key: str
    protocol: str
    use_server_proxy: bool


@dataclass
class FakeHost:
    path: str


@dataclass
class FakeVolume:
    name: str
    host: FakeHost
    mountPath: str
    readOnly: bool = False




@dataclass
class FakeSandboxFilter:
    states: list[str] | None = None
    metadata: dict[str, str] | None = None
    page_size: int | None = None
    page: int | None = None


@dataclass
class FakeWriteEntry:
    path: str
    data: str
    mode: int


@dataclass
class FakeSearchEntry:
    path: str
    pattern: str


@dataclass
class FakeMoveEntry:
    src: str
    dest: str


@dataclass
class FakeRunCommandOpts:
    working_directory: str | None = None


class FakeCommands:
    def __init__(self):
        self.commands = []

    async def run(self, command, *, opts=None):
        self.commands.append((command, opts))
        stdout = ["ok"]
        if command.startswith("cd -- ") and command.endswith(" && pwd"):
            stdout = [command.removeprefix("cd -- ").removesuffix(" && pwd").strip("'")]
        return SimpleNamespace(exit_code=0, logs={"stdout": stdout})


class FakeFiles:
    def __init__(self):
        self.writes = []
        self.deleted = []
        self.searches = []
        self.moves = []

    async def write_files(self, entries):
        self.writes.extend(entries)

    async def read_file(self, path):
        return f"content:{path}"

    async def search(self, entry):
        self.searches.append(entry)
        return [SimpleNamespace(path=f"{entry.path}/a.txt")]

    async def delete_files(self, paths):
        self.deleted.extend(paths)

    async def move_files(self, entries):
        self.moves.extend(entries)


class FakeSandbox:
    create_calls = []
    resume_calls = []

    def __init__(self, sandbox_id="sandbox-1"):
        self.id = sandbox_id
        self.commands = FakeCommands()
        self.files = FakeFiles()
        self.killed = False
        self.renewed = []
        self.paused = False

    @classmethod
    async def create(cls, **kwargs):
        cls.create_calls.append(kwargs)
        return cls()

    @classmethod
    async def resume(cls, **kwargs):
        cls.resume_calls.append(kwargs)
        return cls(kwargs["sandbox_id"])

    async def renew(self, timeout):
        self.renewed.append(timeout)
        return {"renewed": timeout.total_seconds()}

    async def pause(self):
        self.paused = True
        return {"paused": True}

    async def get_info(self):
        return SimpleNamespace(status=SimpleNamespace(state="RUNNING"))

    async def kill(self):
        self.killed = True


class FakeSandboxManager:
    @classmethod
    async def create(cls, **kwargs):
        return cls()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def list_sandbox_infos(self, filter):
        assert filter == FakeSandboxFilter()
        return [SimpleNamespace(id="sandbox-1")]


class FakeSdk:
    Sandbox = FakeSandbox
    SandboxManager = FakeSandboxManager
    ConnectionConfig = FakeConnectionConfig
    Host = FakeHost
    Volume = FakeVolume
    SandboxFilter = FakeSandboxFilter
    WriteEntry = FakeWriteEntry
    SearchEntry = FakeSearchEntry
    MoveEntry = FakeMoveEntry
    RunCommandOpts = FakeRunCommandOpts


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch, tmp_path):
    FakeSandbox.create_calls = []
    FakeSandbox.resume_calls = []
    monkeypatch.setenv("SANDBOX_ENDPOINT", "http://sandbox.test:8090")
    monkeypatch.setenv("SANDBOX_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_HOME_DIR", str(tmp_path))
    monkeypatch.delenv("SANDBOX_IMAGE", raising=False)
    monkeypatch.setattr(agent_sandbox, "_load_opensandbox_sdk", lambda: FakeSdk)


def test_create_uses_default_image_host_path_and_workspace_mount(tmp_path):
    async def run():
        sandbox = AgentSandbox()
        result = await sandbox.create("user_123")

        assert result == {
            "sandbox_id": "sandbox-1",
            "user_id": "user_123",
            "host_path": str(tmp_path / "user_123"),
            "mount_path": WORKSPACE_MOUNT_PATH,
            "image": "ubuntu:22.04",
        }
        assert (tmp_path / "user_123").is_dir()

        call = FakeSandbox.create_calls[0]
        assert call["image"] == "ubuntu:22.04"
        assert call["connection_config"] == FakeConnectionConfig(
            domain="sandbox.test:8090",
            api_key="test-key",
            protocol="http",
            use_server_proxy=False,
        )
        assert call["timeout"] == timedelta(minutes=30)
        volume = call["volumes"][0]
        assert volume.host.path == str(tmp_path / "user_123")
        assert volume.mountPath == "/workspace"
        assert volume.readOnly is False

    import asyncio

    asyncio.run(run())


@pytest.mark.parametrize("user_id", ["", "../user", "a/b", "a\\b", "abc..def"])
def test_create_rejects_unsafe_user_id(user_id):
    async def run():
        with pytest.raises(ValueError):
            await AgentSandbox().create(user_id)

    import asyncio

    asyncio.run(run())


@pytest.mark.asyncio
async def test_context_manager_kills_sandbox_on_success_and_exception():
    async with AgentSandbox("user_123") as sandbox:
        created = sandbox._sandbox
        assert created is not None

    assert created.killed is True
    assert sandbox._sandbox is None

    with pytest.raises(RuntimeError):
        async with AgentSandbox("user_456") as failing:
            created = failing._sandbox
            raise RuntimeError("boom")

    assert created.killed is True


@pytest.mark.asyncio
async def test_command_file_and_lifecycle_methods_delegate_to_sdk():
    sandbox = AgentSandbox(sandbox=FakeSandbox())

    command = await sandbox.run_command("echo ok")
    assert command["sandbox_id"] == "sandbox-1"
    assert command["result"]["exit_code"] == 0
    assert sandbox._sandbox.commands.commands == [
        ("echo ok", FakeRunCommandOpts(working_directory="/workspace"))
    ]

    write = await sandbox.write_file("/workspace/a.txt", "hello")
    assert write == {"sandbox_id": "sandbox-1", "path": "/workspace/a.txt"}
    assert sandbox._sandbox.files.writes == [FakeWriteEntry("/workspace/a.txt", "hello", 0o644)]

    read = await sandbox.read_file("/workspace/a.txt")
    assert read["content"] == "content:/workspace/a.txt"

    listed = await sandbox.list_files()
    assert listed["path"] == "/workspace"
    assert listed["files"] == [{"path": "/workspace/a.txt"}]
    assert sandbox._sandbox.files.searches == [FakeSearchEntry("/workspace", "*")]

    deleted = await sandbox.delete_file("/workspace/a.txt")
    assert deleted == {"sandbox_id": "sandbox-1", "path": "/workspace/a.txt"}
    assert sandbox._sandbox.files.deleted == ["/workspace/a.txt"]

    renewed = await sandbox.renew(15)
    assert renewed["result"] == {"renewed": 900.0}
    assert sandbox._sandbox.renewed == [timedelta(minutes=15)]

    paused = await sandbox.pause()
    assert paused["result"] == {"paused": True}

    info = await sandbox.get_info()
    assert info["info"] == {"status": {"state": "RUNNING"}}

    resumed = await sandbox.resume()
    assert resumed == {"sandbox_id": "sandbox-1"}
    assert FakeSandbox.resume_calls[0]["sandbox_id"] == "sandbox-1"

    listed_sandboxes = await sandbox.list_sandboxes()
    assert listed_sandboxes == {"sandboxes": [{"id": "sandbox-1"}]}

    killed = await sandbox.kill()
    assert killed == {"sandbox_id": "sandbox-1", "killed": True}
    assert sandbox._sandbox is None


@pytest.mark.asyncio
async def test_working_directory_and_relative_paths():
    sandbox = AgentSandbox(sandbox=FakeSandbox())

    assert await sandbox.pwd() == {"sandbox_id": "sandbox-1", "path": "/workspace"}

    cd_result = await sandbox.cd("project")
    assert cd_result == {"sandbox_id": "sandbox-1", "path": "/workspace/project"}

    await sandbox.run_command("pwd")
    assert sandbox._sandbox.commands.commands[-1] == (
        "pwd",
        FakeRunCommandOpts(working_directory="/workspace/project"),
    )

    write = await sandbox.write_file("a.txt", "hello")
    assert write == {"sandbox_id": "sandbox-1", "path": "/workspace/project/a.txt"}

    read = await sandbox.read_file("a.txt")
    assert read["path"] == "/workspace/project/a.txt"

    listed = await sandbox.list_files(".", "*.py")
    assert listed["path"] == "/workspace/project"
    assert sandbox._sandbox.files.searches[-1] == FakeSearchEntry("/workspace/project", "*.py")

    deleted = await sandbox.delete_file("a.txt")
    assert deleted == {"sandbox_id": "sandbox-1", "path": "/workspace/project/a.txt"}


@pytest.mark.asyncio
async def test_copy_and_rename_use_resolved_paths():
    sandbox = AgentSandbox(sandbox=FakeSandbox())
    await sandbox.cd("/workspace/project")

    copied = await sandbox.copy("src dir", "dest dir")
    assert copied["src"] == "/workspace/project/src dir"
    assert copied["dest"] == "/workspace/project/dest dir"
    assert sandbox._sandbox.commands.commands[-1] == (
        "cp -R -- '/workspace/project/src dir' '/workspace/project/dest dir'",
        FakeRunCommandOpts(working_directory="/workspace/project"),
    )

    renamed = await sandbox.rename("old.txt", "new.txt")
    assert renamed == {
        "sandbox_id": "sandbox-1",
        "src": "/workspace/project/old.txt",
        "dest": "/workspace/project/new.txt",
    }
    assert sandbox._sandbox.files.moves == [
        FakeMoveEntry("/workspace/project/old.txt", "/workspace/project/new.txt")
    ]


@pytest.mark.asyncio
async def test_methods_require_created_sandbox():
    with pytest.raises(RuntimeError):
        await AgentSandbox().run_command("echo ok")


def test_connection_config_can_enable_server_proxy(monkeypatch):
    monkeypatch.setenv("SANDBOX_USE_SERVER_PROXY", "true")

    config = agent_sandbox._connection_config(FakeConnectionConfig)

    assert config.use_server_proxy is True
