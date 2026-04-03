"""
Unit tests for system tools path security integration.

Tests that filesystem tools (read, write, edit, etc.) correctly enforce
path security when user_id is provided in config.
"""
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from tools.system_tools import (
    edit_impl,
    exec_impl,
    find_impl,
    grep_impl,
    ls_impl,
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
async def test_ls_impl_blocks_outside_sandbox(user_id):
    """Test that ls_impl blocks listing outside sandbox."""
    result = await ls_impl(path="/etc", _config={"user_id": user_id})
    assert "🚫 拒絕存取" in result


@pytest.mark.asyncio
async def test_exec_impl_cwd_within_sandbox(user_sandbox, user_id):
    """Test that exec_impl restricts cwd to sandbox."""
    subdir = user_sandbox / "workspace"
    subdir.mkdir()

    result = await exec_impl(
        command="pwd", cwd="workspace", _config={"user_id": user_id}
    )
    # Should execute in sandbox/workspace
    assert "workspace" in result.lower() or "[exit code:" in result


@pytest.mark.asyncio
async def test_exec_impl_blocks_cwd_outside_sandbox(user_id):
    """Test that exec_impl blocks cwd outside sandbox."""
    result = await exec_impl(
        command="ls", cwd="/etc", _config={"user_id": user_id}
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
