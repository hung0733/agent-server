#!/usr/bin/env python3
"""Smoke test AgentSandbox against a real OpenSandbox server.

Usage:
    python -m scripts.test_agent_sandbox
    python -m scripts.test_agent_sandbox my_user_id
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.i18n import t
from backend.sandbox import AgentSandbox


DEFAULT_USER_ID = "sandbox_smoke_test"
SMOKE_FILE_PATH = "/workspace/smoke-test.txt"
SMOKE_FILE_CONTENT = "agent sandbox smoke test"
SMOKE_COMMAND = "pwd && ls -la /workspace && echo sandbox-ok"
VERIFY_COMMAND = f"cat {SMOKE_FILE_PATH}"

logger = logging.getLogger(__name__)


def _print_step(message_key: str, *args: Any) -> None:
    print(t(message_key) % args if args else t(message_key))


async def _run_step(
    name: str,
    action: Callable[[], Any],
) -> Any:
    _print_step("scripts.test_agent_sandbox.step_start", name)
    result = action()
    if hasattr(result, "__await__"):
        result = await result
    _print_step("scripts.test_agent_sandbox.step_ok", name)
    return result


async def run_smoke_test(user_id: str = DEFAULT_USER_ID) -> int:
    load_dotenv()
    sandbox = AgentSandbox(user_id=user_id, timeout_minutes=10)
    try:
        _print_step("scripts.test_agent_sandbox.start", user_id)
        create_result = await _run_step("create", sandbox.create)
        _print_step("scripts.test_agent_sandbox.sandbox_id", create_result.get("sandbox_id"))

        await _run_step("get_info", sandbox.get_info)
        await _run_step("run_command", lambda: sandbox.run_command(SMOKE_COMMAND))
        await _run_step("write_file", lambda: sandbox.write_file(SMOKE_FILE_PATH, SMOKE_FILE_CONTENT))

        read_result = await _run_step("read_file", lambda: sandbox.read_file(SMOKE_FILE_PATH))
        if read_result.get("content") != SMOKE_FILE_CONTENT:
            raise RuntimeError(t("scripts.test_agent_sandbox.read_mismatch"))

        await _run_step("list_files", lambda: sandbox.list_files("/workspace", "smoke-test.txt"))
        await _run_step("renew", lambda: sandbox.renew(10))
        await _run_step("pause", sandbox.pause)
        await _run_step("resume", sandbox.resume)

        verify_result = await _run_step("run_command_after_resume", lambda: sandbox.run_command(VERIFY_COMMAND))
        if SMOKE_FILE_CONTENT not in str(verify_result.get("result")):
            raise RuntimeError(t("scripts.test_agent_sandbox.verify_command_mismatch"))

        await _run_step("delete_file", lambda: sandbox.delete_file(SMOKE_FILE_PATH))
        await _run_step("list_sandboxes", sandbox.list_sandboxes)
        await _run_step("kill", sandbox.kill)
        _print_step("scripts.test_agent_sandbox.success")
        return 0
    except Exception as exc:
        logger.exception("%s: %s", t("scripts.test_agent_sandbox.failed"), exc)
        print(f"{t('scripts.test_agent_sandbox.failed')}: {exc}")
        return 1
    finally:
        kill_result = await sandbox.kill()
        if kill_result.get("killed"):
            _print_step("scripts.test_agent_sandbox.cleanup_killed", kill_result.get("sandbox_id"))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = argv if argv is not None else sys.argv[1:]
    user_id = args[0] if args else DEFAULT_USER_ID
    return asyncio.run(run_smoke_test(user_id))


if __name__ == "__main__":
    raise SystemExit(main())
