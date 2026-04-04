# pyright: reportMissingImports=false
"""
System / filesystem tool implementations for agents.

Provides async functions for agents to interact with the local filesystem
and execute shell commands:
  - read_impl       : Read file contents
  - write_impl      : Create or overwrite a file
  - edit_impl       : Make a precise find-and-replace edit
  - apply_patch_impl: Apply a unified diff patch to one or more files
  - grep_impl       : Search file contents for a regex pattern
  - find_impl       : Find files matching a glob pattern
  - ls_impl         : List directory contents
  - exec_impl       : Run a shell command and return output
  - process_impl    : Manage background shell sessions (start / status / kill)

All functions are raw async callables (not @tool decorated) that are
wrapped into StructuredTools by tools.py.

Import path: tools.system_tools
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from i18n import _
from tools.path_security import (
    PathSecurityError,
    VIRTUAL_SANDBOX_PREFIXES,
    get_user_sandbox_dir,
    resolve_safe_path,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level background-process registry (keyed by handle string)
# ---------------------------------------------------------------------------
_PROCESSES: dict[str, asyncio.subprocess.Process] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(path: str, base_dir: str | None, user_id: str = "") -> Path:
    """Resolve a path with optional security validation.

    Args:
        path: Absolute or relative file path.
        base_dir: Optional base directory from tool config.
        user_id: User ID for path security validation (if provided).

    Returns:
        Resolved Path object.

    Raises:
        PathSecurityError: If user_id is provided and path is outside sandbox.
    """
    if user_id:
        # Use secure path resolution
        return resolve_safe_path(path, user_id, base_dir)
    else:
        # Legacy behavior for backward compatibility
        p = Path(path)
        if not p.is_absolute() and base_dir:
            p = Path(base_dir) / p
        return p.resolve()


def _resolve_working_dir(base_dir: str | None, user_id: str = "") -> Path:
    """Resolve the effective working directory for a tool invocation."""
    if user_id:
        if base_dir:
            return _resolve_path(base_dir, None, user_id)
        return _resolve_path(".", None, user_id)

    if base_dir:
        return Path(base_dir).resolve()
    return Path.cwd().resolve()


def _display_path(path: Path, user_id: str = "") -> str:
    """Render a sandbox path without leaking the real AGENT_HOME_DIR root."""
    if not user_id:
        return str(path)

    sandbox_dir = get_user_sandbox_dir(user_id)
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(sandbox_dir)
    except ValueError:
        return str(path)

    virtual_prefix = VIRTUAL_SANDBOX_PREFIXES[0]
    virtual_parts = virtual_prefix.parts[1:]
    if relative.parts[: len(virtual_parts)] == virtual_parts:
        return str(Path("/") / relative)
    return str(virtual_prefix / relative)


def _extract_patch_target_paths(patch: str) -> list[str]:
    """Extract candidate target paths from unified diff headers."""
    targets: list[str] = []
    for line in patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw_path = line[4:].strip()
        if not raw_path or raw_path == "/dev/null":
            continue
        raw_path = raw_path.split("\t", 1)[0].strip()
        targets.append(raw_path)
    return targets


def _normalize_patch_path(raw_path: str, strip: int) -> str:
    """Apply patch -p stripping semantics to a diff header path."""
    path_obj = Path(raw_path)
    if path_obj.is_absolute():
        return raw_path

    anchor = path_obj.anchor
    parts = [part for part in path_obj.parts if part and part != anchor]
    if strip > 0:
        parts = parts[strip:]
    if not parts:
        return "."
    normalized = Path(*parts)
    return str(normalized)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

async def read_impl(
    path: str,
    encoding: str = "utf-8",
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Read and return the contents of a file.

    Args:
        path: Absolute or relative file path.
        encoding: Text encoding (default: utf-8).
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        File contents as a string, or an error message.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    try:
        resolved = _resolve_path(path, _config.get("base_dir"), user_id)
    except PathSecurityError as exc:
        logger.warning(_("[read] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[read] 讀取檔案: %s"), resolved)
    try:
        return resolved.read_text(encoding=encoding)
    except Exception as exc:
        logger.error(_("[read] ❌ 讀取失敗: %s"), exc)
        return _("❌ 讀取失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

async def write_impl(
    path: str,
    content: str,
    encoding: str = "utf-8",
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Create or overwrite a file with the given content.

    Args:
        path: Absolute or relative file path.
        content: Text content to write.
        encoding: Text encoding (default: utf-8).
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Success or error message.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    try:
        resolved = _resolve_path(path, _config.get("base_dir"), user_id)
    except PathSecurityError as exc:
        logger.warning(_("[write] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[write] 寫入檔案: %s (%d bytes)"), resolved, len(content))
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
        return _("✅ 已寫入: %s") % _display_path(resolved, user_id)
    except Exception as exc:
        logger.error(_("[write] ❌ 寫入失敗: %s"), exc)
        return _("❌ 寫入失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------

async def edit_impl(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Make a precise string replacement in a file.

    Args:
        path: File path.
        old_string: Exact text to find.
        new_string: Replacement text.
        replace_all: If True, replace every occurrence; otherwise only the first.
        encoding: Text encoding (default: utf-8).
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Success message with replacement count, or an error message.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    try:
        resolved = _resolve_path(path, _config.get("base_dir"), user_id)
    except PathSecurityError as exc:
        logger.warning(_("[edit] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[edit] 編輯檔案: %s"), resolved)
    try:
        original = resolved.read_text(encoding=encoding)
        if old_string not in original:
            return _("❌ 找不到要替換的字串: %r") % old_string

        if replace_all:
            updated = original.replace(old_string, new_string)
            count = original.count(old_string)
        else:
            updated = original.replace(old_string, new_string, 1)
            count = 1

        resolved.write_text(updated, encoding=encoding)
        return _("✅ 已替換 %d 處: %s") % (count, _display_path(resolved, user_id))
    except Exception as exc:
        logger.error(_("[edit] ❌ 編輯失敗: %s"), exc)
        return _("❌ 編輯失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------

async def apply_patch_impl(
    patch: str,
    strip: int = 1,
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Apply a unified diff patch using the system ``patch`` command.

    Args:
        patch: Unified diff text (as produced by ``git diff`` or ``diff -u``).
        strip: Number of leading path components to strip (``patch -p``).
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` (working directory).

    Returns:
        Patch output or error message.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")

    try:
        cwd = str(_resolve_working_dir(_config.get("base_dir"), user_id))
        for raw_path in _extract_patch_target_paths(patch):
            candidate = _normalize_patch_path(raw_path, strip)
            _resolve_path(candidate, cwd, user_id)
    except PathSecurityError as exc:
        logger.warning(_("[apply_patch] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[apply_patch] 套用 patch，cwd=%s"), cwd)
    try:
        proc = await asyncio.create_subprocess_exec(
            "patch", f"-p{strip}", "--batch",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=patch.encode()),
            timeout=30,
        )
        if proc.returncode != 0:
            return _("❌ patch 失敗 (rc=%d):\n%s") % (proc.returncode, stderr.decode())
        return _("✅ patch 成功:\n%s") % stdout.decode()
    except Exception as exc:
        logger.error(_("[apply_patch] ❌ 失敗: %s"), exc)
        return _("❌ apply_patch 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------

async def grep_impl(
    pattern: str,
    path: str = ".",
    recursive: bool = True,
    ignore_case: bool = False,
    include: str = "",
    max_results: int = 100,
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Search file contents for a regex pattern.

    Args:
        pattern: Regular expression to search for.
        path: File or directory to search in.
        recursive: Search subdirectories (default True).
        ignore_case: Case-insensitive matching.
        include: Glob pattern to filter filenames (e.g. ``*.py``).
        max_results: Maximum number of matching lines to return.
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Matching lines formatted as ``file:line:content``.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    try:
        resolved = _resolve_path(path, _config.get("base_dir"), user_id)
    except PathSecurityError as exc:
        logger.warning(_("[grep] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    flags = re.IGNORECASE if ignore_case else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return _("❌ 無效的正則表達式: %s") % str(exc)

    results: list[str] = []
    search_files: list[Path] = []

    if resolved.is_file():
        search_files = [resolved]
    else:
        glob_pattern = f"**/{include}" if include else "**/*"
        search_files = [
            p for p in resolved.glob(glob_pattern) if p.is_file()
        ] if recursive else [
            p for p in resolved.glob(include or "*") if p.is_file()
        ]

    for file_path in search_files:
        try:
            text = file_path.read_text(errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                results.append(f"{_display_path(file_path, user_id)}:{lineno}:{line}")
                if len(results) >= max_results:
                    results.append(
                        _("... (已達上限 %d 筆，請縮小搜索範圍)") % max_results
                    )
                    return "\n".join(results)

    if not results:
        return _("🔍 無符合結果: %s") % pattern
    return "\n".join(results)


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------

async def find_impl(
    pattern: str,
    path: str = ".",
    max_results: int = 200,
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g. ``**/*.py``, ``src/*.ts``).
        path: Root directory to search from.
        max_results: Maximum number of results to return.
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Newline-separated list of matching file paths.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    try:
        root = _resolve_path(path, _config.get("base_dir"), user_id)
    except PathSecurityError as exc:
        logger.warning(_("[find] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[find] 搜索: %s in %s"), pattern, root)
    try:
        matches = sorted(root.glob(pattern))[:max_results]
        if not matches:
            return _("🔍 無符合結果: %s") % pattern
        return "\n".join(_display_path(p, user_id) for p in matches)
    except Exception as exc:
        logger.error(_("[find] ❌ 失敗: %s"), exc)
        return _("❌ find 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

async def ls_impl(
    path: str = ".",
    show_hidden: bool = False,
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """List the contents of a directory.

    Args:
        path: Directory path to list.
        show_hidden: Include hidden (dot-prefixed) entries.
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Formatted directory listing.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    try:
        resolved = _resolve_path(path, _config.get("base_dir"), user_id)
    except PathSecurityError as exc:
        logger.warning(_("[ls] 🚫 路徑安全檢查失敗: %s"), exc)
        return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[ls] 列出目錄: %s"), resolved)
    try:
        entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines: list[str] = [_("📂 %s") % _display_path(resolved, user_id), ""]
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            kind = "📄" if entry.is_file() else "📁"
            size = f"  ({entry.stat().st_size:,} bytes)" if entry.is_file() else ""
            lines.append(f"  {kind} {entry.name}{size}")
        return "\n".join(lines) if len(lines) > 2 else _("📂 目錄為空")
    except Exception as exc:
        logger.error(_("[ls] ❌ 失敗: %s"), exc)
        return _("❌ ls 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------

async def exec_impl(
    command: str,
    cwd: str = "",
    timeout: int = 60,
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Run a shell command and return its combined output.

    Args:
        command: Shell command string to execute.
        cwd: Working directory (defaults to ``base_dir`` config or cwd).
        timeout: Timeout in seconds (max 300, default 60).
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Combined stdout + stderr, with exit code appended.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")
    timeout = min(timeout, 300)

    if user_id:
        return _("🚫 拒絕存取: sandbox 模式唔支援 exec")

    # Determine working directory and validate if user_id is set
    if cwd:
        try:
            working_dir_path = _resolve_path(cwd, _config.get("base_dir"), user_id)
            working_dir = str(working_dir_path)
        except PathSecurityError as exc:
            logger.warning(_("[exec] 🚫 路徑安全檢查失敗: %s"), exc)
            return _("🚫 拒絕存取: %s") % str(exc)
    else:
        # Use base_dir or default, but validate if user_id is set
        try:
            working_dir_path = _resolve_working_dir(_config.get("base_dir"), user_id)
            working_dir = str(working_dir_path)
        except PathSecurityError as exc:
            logger.warning(_("[exec] 🚫 路徑安全檢查失敗: %s"), exc)
            return _("🚫 拒絕存取: %s") % str(exc)

    logger.info(_("[exec] 執行命令: %s (cwd=%s)"), command, working_dir)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=working_dir,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
        return f"{output}\n[exit code: {proc.returncode}]"
    except asyncio.TimeoutError:
        return _("❌ 命令超時 (%ds): %s") % (timeout, command)
    except Exception as exc:
        logger.error(_("[exec] ❌ 失敗: %s"), exc)
        return _("❌ exec 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# process  (background process management)
# ---------------------------------------------------------------------------

async def process_impl(
    action: str,
    command: str = "",
    handle: str = "",
    cwd: str = "",
    agent_db_id: str = "",
    _config: dict[str, Any] | None = None,
) -> str:
    """Manage background shell sessions.

    Args:
        action: One of ``start``, ``status``, ``kill``, ``list``.
        command: Shell command to start (required for ``start``).
        handle: Process handle returned by ``start`` (required for ``status``/``kill``).
        cwd: Working directory for ``start``.
        agent_db_id: Auto-injected agent ID.
        _config: Tool config with optional ``base_dir`` and ``user_id`` (for path security).

    Returns:
        Result message.
    """
    _config = _config or {}
    user_id = _config.get("user_id", "")

    if user_id:
        return _("🚫 拒絕存取: sandbox 模式唔支援 process")

    if action == "start":
        if not command:
            return _("❌ action=start 需要提供 command")

        # Determine and validate working directory
        if cwd:
            try:
                working_dir_path = _resolve_path(cwd, _config.get("base_dir"), user_id)
                working_dir = str(working_dir_path)
            except PathSecurityError as exc:
                logger.warning(_("[process] 🚫 路徑安全檢查失敗: %s"), exc)
                return _("🚫 拒絕存取: %s") % str(exc)
        else:
            try:
                working_dir_path = _resolve_working_dir(_config.get("base_dir"), user_id)
                working_dir = str(working_dir_path)
            except PathSecurityError as exc:
                logger.warning(_("[process] 🚫 路徑安全檢查失敗: %s"), exc)
                return _("🚫 拒絕存取: %s") % str(exc)

        key = f"{agent_db_id}:{command[:40]}"
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=working_dir,
            )
            _PROCESSES[key] = proc
            logger.info(_("[process] 已啟動後台進程: handle=%s pid=%s"), key, proc.pid)
            return _("✅ 後台進程已啟動\nhandle: %s\npid: %s") % (key, proc.pid)
        except Exception as exc:
            return _("❌ 啟動失敗: %s") % str(exc)

    elif action == "status":
        if not handle or handle not in _PROCESSES:
            return _("❌ 找不到進程 handle: %s") % handle
        proc = _PROCESSES[handle]
        if proc.returncode is None:
            return _("⏳ 進程仍在運行\nhandle: %s\npid: %s") % (handle, proc.pid)
        return _("✅ 進程已結束\nhandle: %s\nexit code: %s") % (handle, proc.returncode)

    elif action == "kill":
        if not handle or handle not in _PROCESSES:
            return _("❌ 找不到進程 handle: %s") % handle
        proc = _PROCESSES.pop(handle)
        try:
            proc.kill()
            return _("✅ 進程已終止\nhandle: %s") % handle
        except Exception as exc:
            return _("❌ 終止失敗: %s") % str(exc)

    elif action == "list":
        if not _PROCESSES:
            return _("📭 沒有後台進程")
        lines = [_("📋 後台進程列表:")]
        for key, proc in _PROCESSES.items():
            status = _("運行中") if proc.returncode is None else _("已結束 (rc=%s)") % proc.returncode
            lines.append(f"  • {key}  pid={proc.pid}  {status}")
        return "\n".join(lines)

    else:
        return _("❌ 未知 action: %s (有效值: start, status, kill, list)") % action
