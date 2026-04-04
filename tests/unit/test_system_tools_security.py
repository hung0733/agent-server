"""
Unit tests for system tools path security integration.

Tests that filesystem tools (read, write, edit, etc.) correctly enforce
path security when user_id is provided in config.
"""
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from sandbox.models import SandboxRequest
from tools.system_tools import (
    apply_patch_impl,
    edit_impl,
    exec_impl,
    find_impl,
    grep_impl,
    ls_impl,
    process_impl,
    read_impl,
    write_impl,
)


@pytest.fixture
def temp_agent_home(monkeypatch):
    """Create a temporary agent home directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("AGENT_HOME_DIR", tmpdir)
        yield Path(tmpdir)


@pytest.fixture
def user_id():
    """Generate a test user ID."""
    return str(uuid4())


@pytest.fixture
def user_sandbox(temp_agent_home, user_id):
    """Create and return user sandbox directory."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def fake_provider(monkeypatch):
    class FakeProvider:
        def __init__(self):
            self.exec_calls = []
            self.process_calls = []

        async def exec(self, request: SandboxRequest, command: str, cwd: str, timeout: int):
            self.exec_calls.append((request, command, cwd, timeout))
            return f"sandbox:{command}:{cwd or '.'}:{timeout}"

        async def start_process(self, request: SandboxRequest, command: str, cwd: str):
            self.process_calls.append((request, command, cwd))
            return {"handle": "proc-1", "status": "running", "cwd": cwd}

        async def get_process(self, request: SandboxRequest, process_handle: str):
            return {"handle": process_handle, "status": "running"}

        async def kill_process(self, request: SandboxRequest, process_handle: str):
            return {"handle": process_handle, "status": "killed"}

    provider = FakeProvider()
    monkeypatch.setattr("tools.system_tools.get_sandbox_provider", lambda _config=None: provider)
    return provider


@pytest.mark.asyncio
async def test_read_impl_within_sandbox(user_sandbox, user_id):
    """Test that read_impl works within sandbox."""
    test_file = user_sandbox / "test.txt"
    test_file.write_text("Hello, World!")

    result = await read_impl(
        path="test.txt", _config={"user_id": user_id}
    )
    assert result == "Hello, World!"


@pytest.mark.asyncio
async def test_read_impl_blocks_outside_sandbox(user_id):
    """Test that read_impl blocks access outside sandbox."""
    result = await read_impl(
        path="/etc/passwd", _config={"user_id": user_id}
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_read_impl_blocks_path_traversal(user_id):
    """Test that read_impl blocks path traversal."""
    result = await read_impl(
        path="../../../etc/passwd", _config={"user_id": user_id}
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_write_impl_within_sandbox(user_sandbox, user_id):
    """Test that write_impl works within sandbox."""
    result = await write_impl(
        path="output.txt",
        content="Test content",
        _config={"user_id": user_id},
    )
    assert "✅ 已寫入" in result

    # Verify file was created
    output_file = user_sandbox / "output.txt"
    assert output_file.exists()
    assert output_file.read_text() == "Test content"


@pytest.mark.asyncio
async def test_write_impl_blocks_outside_sandbox(user_id):
    """Test that write_impl blocks writing outside sandbox."""
    result = await write_impl(
        path="/tmp/evil.txt",
        content="Evil content",
        _config={"user_id": user_id},
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_write_impl_creates_subdirectories(user_sandbox, user_id):
    """Test that write_impl can create nested directories."""
    result = await write_impl(
        path="data/subfolder/file.txt",
        content="Nested file",
        _config={"user_id": user_id},
    )
    assert "✅ 已寫入" in result

    nested_file = user_sandbox / "data/subfolder/file.txt"
    assert nested_file.exists()
    assert nested_file.read_text() == "Nested file"


@pytest.mark.asyncio
async def test_edit_impl_within_sandbox(user_sandbox, user_id):
    """Test that edit_impl works within sandbox."""
    test_file = user_sandbox / "edit.txt"
    test_file.write_text("Hello World")

    result = await edit_impl(
        path="edit.txt",
        old_string="World",
        new_string="Python",
        _config={"user_id": user_id},
    )
    assert "✅ 已替換" in result
    assert test_file.read_text() == "Hello Python"


@pytest.mark.asyncio
async def test_edit_impl_blocks_outside_sandbox(user_id):
    """Test that edit_impl blocks editing outside sandbox."""
    result = await edit_impl(
        path="/etc/hosts",
        old_string="localhost",
        new_string="evil",
        _config={"user_id": user_id},
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_grep_impl_within_sandbox(user_sandbox, user_id):
    """Test that grep_impl works within sandbox."""
    test_file = user_sandbox / "search.txt"
    test_file.write_text("Line 1\\nLine 2 with pattern\\nLine 3")

    result = await grep_impl(
        pattern="pattern", path=".", _config={"user_id": user_id}
    )
    assert "pattern" in result or "🔍 無符合結果" in result


@pytest.mark.asyncio
async def test_find_and_grep_redact_real_sandbox_paths(user_sandbox, user_id):
    """Find and grep results should not leak the real sandbox root."""
    project_dir = user_sandbox / "mnt/data/workspace/castle-stamp-app/src"
    project_dir.mkdir(parents=True, exist_ok=True)
    target_file = project_dir / "route.ts"
    target_file.write_text("export const city = 'Central';\n")

    find_result = await find_impl(
        pattern="**/*.ts",
        path="/mnt/data/workspace/castle-stamp-app/src",
        _config={"user_id": user_id},
    )
    grep_result = await grep_impl(
        pattern="Central",
        path="/mnt/data/workspace/castle-stamp-app/src",
        _config={"user_id": user_id},
    )

    assert str(user_sandbox) not in find_result
    assert str(user_sandbox) not in grep_result
    assert "/mnt/data/workspace/castle-stamp-app/src/route.ts" in find_result
    assert "/mnt/data/workspace/castle-stamp-app/src/route.ts:1:export const city = 'Central';" in grep_result


@pytest.mark.asyncio
async def test_grep_impl_blocks_outside_sandbox(user_id):
    """Test that grep_impl blocks searching outside sandbox."""
    result = await grep_impl(
        pattern="root", path="/etc", _config={"user_id": user_id}
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_find_impl_within_sandbox(user_sandbox, user_id):
    """Test that find_impl works within sandbox."""
    (user_sandbox / "file1.txt").touch()
    (user_sandbox / "file2.py").touch()

    result = await find_impl(
        pattern="*.txt", _config={"user_id": user_id}
    )
    assert "file1.txt" in result or "🔍 無符合結果" in result


@pytest.mark.asyncio
async def test_find_impl_blocks_outside_sandbox(user_id):
    """Test that find_impl blocks searching outside sandbox."""
    result = await find_impl(
        pattern="*.conf", path="/etc", _config={"user_id": user_id}
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_ls_impl_within_sandbox(user_sandbox, user_id):
    """Test that ls_impl works within sandbox."""
    (user_sandbox / "file1.txt").touch()
    (user_sandbox / "file2.txt").touch()

    result = await ls_impl(path=".", _config={"user_id": user_id})
    assert "file1.txt" in result or "📂" in result


@pytest.mark.asyncio
async def test_ls_impl_redacts_real_sandbox_path(user_sandbox, user_id):
    """Sandbox listings should expose virtual paths, not AGENT_HOME_DIR paths."""
    project_dir = user_sandbox / "mnt/data/workspace/castle-stamp-app/src/app/api/cities"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "route.ts").write_text("export const GET = () => null;\n")

    result = await ls_impl(
        path="/mnt/data/workspace/castle-stamp-app/src/app/api/cities",
        _config={"user_id": user_id},
    )

    assert str(user_sandbox) not in result
    assert "/mnt/data/workspace/castle-stamp-app/src/app/api/cities" in result
    assert "route.ts" in result


@pytest.mark.asyncio
async def test_ls_impl_blocks_outside_sandbox(user_id):
    """Test that ls_impl blocks listing outside sandbox."""
    result = await ls_impl(path="/etc", _config={"user_id": user_id})
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_exec_impl_cwd_within_sandbox(user_sandbox, user_id, fake_provider):
    """Sandboxed exec should be routed through sandbox provider."""
    subdir = user_sandbox / "workspace"
    subdir.mkdir()

    result = await exec_impl(
        command="pwd", cwd="workspace", _config={"user_id": user_id}
    )
    assert result == "sandbox:pwd:workspace:60"
    assert fake_provider.exec_calls[0][1:] == ("pwd", "workspace", 60)


@pytest.mark.asyncio
async def test_write_and_read_impl_map_absolute_style_paths_into_sandbox(user_sandbox, user_id):
    """Absolute-style tool paths should be sandbox-rooted for agents."""
    virtual_path = "/mnt/data/workspace/castle-stamp-app/package.json"

    write_result = await write_impl(
        path=virtual_path,
        content='{"name":"castle-stamp-app"}',
        _config={"user_id": user_id},
    )

    assert "🚫 拒絕存取" not in write_result
    expected_file = user_sandbox / "mnt/data/workspace/castle-stamp-app/package.json"
    assert expected_file.exists()

    read_result = await read_impl(path=virtual_path, _config={"user_id": user_id})

    assert 'castle-stamp-app' in read_result


@pytest.mark.asyncio
async def test_exec_impl_blocks_cwd_outside_sandbox(user_id, fake_provider):
    """Sandboxed exec still blocks cwd outside sandbox."""
    result = await exec_impl(
        command="ls", cwd="/etc", _config={"user_id": user_id}
    )
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_exec_impl_without_cwd_defaults_to_user_sandbox(user_sandbox, user_id, fake_provider):
    """Sandboxed exec defaults cwd to user sandbox root."""
    result = await exec_impl(command="pwd", _config={"user_id": user_id})

    assert result == "sandbox:pwd:.:60"
    assert fake_provider.exec_calls[0][2] == "."


@pytest.mark.asyncio
async def test_process_impl_without_cwd_defaults_to_user_sandbox(user_sandbox, user_id, fake_provider):
    """Sandboxed processes should be created through provider."""
    result = await process_impl(
        action="start",
        command="pwd > process_pwd.txt",
        _config={"user_id": user_id},
    )

    assert "proc-1" in result
    assert fake_provider.process_calls[0][1:] == ("pwd > process_pwd.txt", ".")


@pytest.mark.asyncio
async def test_exec_impl_allows_container_scoped_absolute_paths(user_id, fake_provider):
    """Absolute paths in command are delegated to sandbox, not host exec."""
    result = await exec_impl(command="cat /etc/passwd", _config={"user_id": user_id})

    assert result == "sandbox:cat /etc/passwd:.:60"


@pytest.mark.asyncio
async def test_process_impl_delegates_absolute_paths_to_sandbox(user_id, fake_provider):
    """Absolute paths in process commands are delegated to sandbox runtime."""
    result = await process_impl(
        action="start",
        command="cat /etc/hostname > leak.txt",
        _config={"user_id": user_id},
    )

    assert "proc-1" in result


@pytest.mark.asyncio
async def test_apply_patch_impl_blocks_base_dir_outside_sandbox(user_sandbox, user_id):
    """Patch application should reject a base dir outside sandbox."""
    patch = """--- a/test.txt\n+++ b/test.txt\n@@ -0,0 +1 @@\n+hello\n"""

    result = await apply_patch_impl(
        patch=patch,
        _config={"user_id": user_id, "base_dir": "/etc"},
    )

    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_apply_patch_impl_blocks_patch_target_outside_sandbox(user_sandbox, user_id):
    """Patch application should reject targets outside sandbox even with safe base dir."""
    patch = """--- /etc/passwd\n+++ /etc/passwd\n@@ -1 +1 @@\n-root\n+agent\n"""

    result = await apply_patch_impl(
        patch=patch,
        _config={"user_id": user_id, "base_dir": str(user_sandbox)},
    )

    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_tools_without_user_id_work_normally():
    """Test that tools work without user_id (backward compatibility)."""
    # Without user_id, should use current working directory
    result = await read_impl(path="README.md", _config={})
    # Should either read the file or fail with file not found, not security error
    assert "🚫 拒絕存取" not in result


@pytest.mark.asyncio
async def test_multiple_users_isolated(temp_agent_home):
    """Test that different users cannot access each other's files."""
    user1_id = str(uuid4())
    user2_id = str(uuid4())

    # User 1 creates a file
    sandbox1 = temp_agent_home / user1_id
    sandbox1.mkdir(parents=True, exist_ok=True)
    file1 = sandbox1 / "private.txt"
    file1.write_text("User 1 secret")

    # User 2 tries to read User 1's file
    user1_file_path = str(file1)
    result = await read_impl(
        path=user1_file_path, _config={"user_id": user2_id}
    )
    assert "🚫 拒絕存取" in result
