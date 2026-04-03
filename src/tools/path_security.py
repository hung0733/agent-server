"""
Path security module for agent filesystem operations.

Ensures agents can only access files within their designated home directory
(AGENT_HOME_DIR/{user_id}) to prevent unauthorized access to other users'
files or system files.

Import path: tools.path_security
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from i18n import _

if TYPE_CHECKING:
    pass


class PathSecurityError(Exception):
    """Raised when an agent attempts to access a path outside their sandbox."""

    pass


def get_agent_home_dir() -> Path:
    """Get the base agent home directory from environment.

    Returns:
        Path object pointing to AGENT_HOME_DIR.

    Raises:
        RuntimeError: If AGENT_HOME_DIR is not configured.
    """
    home_dir = os.environ.get("AGENT_HOME_DIR")
    if not home_dir:
        raise RuntimeError(_("環境變數 AGENT_HOME_DIR 未設定"))
    return Path(home_dir).resolve()


def get_user_sandbox_dir(user_id: str) -> Path:
    """Get the sandbox directory for a specific user.

    Args:
        user_id: User identifier (typically UUID).

    Returns:
        Path object pointing to AGENT_HOME_DIR/{user_id}.

    Raises:
        RuntimeError: If AGENT_HOME_DIR is not configured.
        ValueError: If user_id is empty or contains path traversal attempts.
    """
    if not user_id:
        raise ValueError(_("user_id 不能為空"))

    # Prevent path traversal in user_id
    if "/" in user_id or "\\" in user_id or ".." in user_id:
        raise ValueError(_("user_id 包含非法字符: %s") % user_id)

    base_dir = get_agent_home_dir()
    return (base_dir / user_id).resolve()


def validate_path_access(
    target_path: str | Path, user_id: str, allow_create: bool = True
) -> Path:
    """Validate that the target path is within the user's sandbox directory.

    Args:
        target_path: The path the agent wants to access.
        user_id: User identifier.
        allow_create: If True, create the sandbox directory if it doesn't exist.

    Returns:
        Resolved Path object if validation succeeds.

    Raises:
        PathSecurityError: If the path is outside the user's sandbox.
        RuntimeError: If AGENT_HOME_DIR is not configured.
        ValueError: If user_id is invalid.
    """
    sandbox_dir = get_user_sandbox_dir(user_id)

    # Create sandbox directory if it doesn't exist
    if allow_create and not sandbox_dir.exists():
        sandbox_dir.mkdir(parents=True, exist_ok=True)

    # Resolve the target path relative to sandbox if it's not absolute
    path_obj = Path(target_path)
    if path_obj.is_absolute():
        target = path_obj.resolve()
    else:
        # Relative paths are resolved relative to sandbox
        target = (sandbox_dir / path_obj).resolve()

    # Check if target is within sandbox
    try:
        # This will raise ValueError if target is not relative to sandbox_dir
        target.relative_to(sandbox_dir)
    except ValueError:
        raise PathSecurityError(
            _("拒絕存取: 路徑 %s 超出允許範圍 %s") % (target, sandbox_dir)
        )

    return target


def resolve_safe_path(
    path: str, user_id: str, base_dir: str | None = None
) -> Path:
    """Resolve a path safely within the user's sandbox.

    If base_dir is provided and matches the user's sandbox, uses it as the
    starting point for relative paths. Otherwise, uses the user's sandbox
    directory directly.

    Args:
        path: Absolute or relative file path.
        user_id: User identifier.
        base_dir: Optional base directory from tool config.

    Returns:
        Resolved Path object within the user's sandbox.

    Raises:
        PathSecurityError: If the resolved path is outside the user's sandbox.
    """
    sandbox_dir = get_user_sandbox_dir(user_id)

    # If base_dir is provided, validate it's within the sandbox
    if base_dir:
        base_path = Path(base_dir).resolve()
        try:
            base_path.relative_to(sandbox_dir)
            # base_dir is valid, use it as the starting point
            resolved = (base_path / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        except ValueError:
            # base_dir is outside sandbox, ignore it and use sandbox_dir
            resolved = (sandbox_dir / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    else:
        # No base_dir, resolve relative to sandbox
        resolved = (sandbox_dir / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()

    # Validate the resolved path is within sandbox
    try:
        resolved.relative_to(sandbox_dir)
    except ValueError:
        raise PathSecurityError(
            _("拒絕存取: 路徑 %s 超出允許範圍 %s") % (resolved, sandbox_dir)
        )

    return resolved
