"""
Unit tests for path security module.

Tests the path validation and sandbox enforcement for agent filesystem tools.
"""
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from tools.path_security import (
    PathSecurityError,
    get_agent_home_dir,
    get_user_sandbox_dir,
    resolve_safe_path,
    validate_path_access,
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


def test_get_agent_home_dir_success(temp_agent_home):
    """Test getting agent home directory when env var is set."""
    home_dir = get_agent_home_dir()
    assert home_dir == temp_agent_home.resolve()


def test_get_agent_home_dir_missing_env(monkeypatch):
    """Test that missing AGENT_HOME_DIR raises RuntimeError."""
    monkeypatch.delenv("AGENT_HOME_DIR", raising=False)
    with pytest.raises(RuntimeError, match="環境變數 AGENT_HOME_DIR 未設定"):
        get_agent_home_dir()


def test_get_user_sandbox_dir_success(temp_agent_home, user_id):
    """Test getting user sandbox directory."""
    sandbox = get_user_sandbox_dir(user_id)
    expected = (temp_agent_home / user_id).resolve()
    assert sandbox == expected


def test_get_user_sandbox_dir_empty_user_id(temp_agent_home):
    """Test that empty user_id raises ValueError."""
    with pytest.raises(ValueError, match="user_id 不能為空"):
        get_user_sandbox_dir("")


def test_get_user_sandbox_dir_path_traversal(temp_agent_home):
    """Test that path traversal in user_id is blocked."""
    with pytest.raises(ValueError, match="user_id 包含非法字符"):
        get_user_sandbox_dir("../../../etc")

    with pytest.raises(ValueError, match="user_id 包含非法字符"):
        get_user_sandbox_dir("user/../other")


def test_validate_path_access_within_sandbox(temp_agent_home, user_id):
    """Test that paths within sandbox are allowed."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)

    # Test absolute path within sandbox
    target = sandbox / "test.txt"
    result = validate_path_access(target, user_id, allow_create=False)
    assert result == target.resolve()

    # Test relative path
    result = validate_path_access("data/file.txt", user_id)
    assert result.is_relative_to(sandbox)


def test_validate_path_access_outside_sandbox(temp_agent_home, user_id):
    """Test that paths outside sandbox are blocked."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)

    # Try to access parent directory
    with pytest.raises(PathSecurityError, match="拒絕存取"):
        validate_path_access(temp_agent_home, user_id, allow_create=False)

    # Try to access system path
    with pytest.raises(PathSecurityError, match="拒絕存取"):
        validate_path_access("/etc/passwd", user_id, allow_create=False)

    # Try path traversal
    with pytest.raises(PathSecurityError, match="拒絕存取"):
        validate_path_access("../../../etc/passwd", user_id, allow_create=True)


def test_validate_path_access_creates_sandbox(temp_agent_home, user_id):
    """Test that sandbox directory is created when allow_create=True."""
    sandbox = temp_agent_home / user_id
    assert not sandbox.exists()

    validate_path_access("test.txt", user_id, allow_create=True)
    assert sandbox.exists()
    assert sandbox.is_dir()


def test_resolve_safe_path_no_base_dir(temp_agent_home, user_id):
    """Test resolving paths without base_dir."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)

    # Relative path should resolve within sandbox
    result = resolve_safe_path("data/file.txt", user_id)
    assert result.is_relative_to(sandbox)
    assert result == (sandbox / "data/file.txt").resolve()

    # Absolute path within sandbox should work
    target = sandbox / "absolute.txt"
    result = resolve_safe_path(str(target), user_id)
    assert result == target


def test_resolve_safe_path_with_valid_base_dir(temp_agent_home, user_id):
    """Test resolving paths with base_dir inside sandbox."""
    sandbox = temp_agent_home / user_id
    project_dir = sandbox / "project"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Relative path with base_dir
    result = resolve_safe_path("src/main.py", user_id, str(project_dir))
    expected = (project_dir / "src/main.py").resolve()
    assert result == expected


def test_resolve_safe_path_with_invalid_base_dir(temp_agent_home, user_id):
    """Test that base_dir outside sandbox is ignored and uses sandbox instead."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)

    # base_dir outside sandbox should be ignored
    outside_dir = "/tmp/outside"
    result = resolve_safe_path("file.txt", user_id, outside_dir)
    # Should resolve to sandbox, not outside_dir
    assert result.is_relative_to(sandbox)
    assert result == (sandbox / "file.txt").resolve()


def test_resolve_safe_path_blocks_traversal(temp_agent_home, user_id):
    """Test that path traversal is blocked even with relative paths."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)

    with pytest.raises(PathSecurityError, match="拒絕存取"):
        resolve_safe_path("../../../etc/passwd", user_id)

    with pytest.raises(PathSecurityError, match="拒絕存取"):
        resolve_safe_path("data/../../../etc/passwd", user_id)


def test_multiple_users_isolated(temp_agent_home):
    """Test that different users have isolated sandboxes."""
    user1_id = str(uuid4())
    user2_id = str(uuid4())

    sandbox1 = get_user_sandbox_dir(user1_id)
    sandbox2 = get_user_sandbox_dir(user2_id)

    # Sandboxes should be different
    assert sandbox1 != sandbox2

    # User 1 cannot access User 2's files
    sandbox1.mkdir(parents=True, exist_ok=True)
    sandbox2.mkdir(parents=True, exist_ok=True)

    user2_file = sandbox2 / "private.txt"
    with pytest.raises(PathSecurityError):
        validate_path_access(user2_file, user1_id, allow_create=False)


def test_symlink_escape_blocked(temp_agent_home, user_id):
    """Test that symlinks cannot escape the sandbox."""
    sandbox = temp_agent_home / user_id
    sandbox.mkdir(parents=True, exist_ok=True)

    # Create a symlink pointing outside sandbox
    outside_target = temp_agent_home / "outside.txt"
    outside_target.write_text("secret")

    symlink = sandbox / "escape_link"
    symlink.symlink_to(outside_target)

    # Following the symlink should be blocked
    with pytest.raises(PathSecurityError, match="拒絕存取"):
        validate_path_access(symlink, user_id, allow_create=False)
