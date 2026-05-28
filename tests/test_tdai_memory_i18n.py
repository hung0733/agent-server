import ast
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from backend.i18n import t
from tdai_memory.manager import MemoryManager


TDAI_MEMORY_DIR = BACKEND_DIR / "tdai_memory"
LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _iter_tdai_memory_trees():
    for path in TDAI_MEMORY_DIR.rglob("*.py"):
        yield path, ast.parse(path.read_text(), filename=str(path))


def test_tdai_memory_i18n_locale_selection(monkeypatch):
    monkeypatch.setenv("LANG_LOCALE", "zh_HK")
    assert t("tdai_memory.manager.initialized") == "MemoryManager 已初始化"

    monkeypatch.setenv("LANG_LOCALE", "en")
    assert t("tdai_memory.manager.initialized") == "MemoryManager initialized"

    monkeypatch.setenv("LANG_LOCALE", "missing")
    assert t("tdai_memory.manager.initialized") == "MemoryManager 已初始化"


@pytest.mark.asyncio
async def test_tdai_memory_invalid_boolean_exception_uses_i18n(monkeypatch):
    monkeypatch.setenv("LANG_LOCALE", "en")
    monkeypatch.setenv("TDAI_MEM_CAPTURE_ENABLED", "maybe")

    with pytest.raises(ValueError, match="TDAI_MEM_CAPTURE_ENABLED must be a boolean value"):
        await MemoryManager.from_env()


def test_tdai_memory_logger_messages_use_i18n():
    offenders = []
    for path, tree in _iter_tdai_memory_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in LOGGER_METHODS or not node.args:
                continue
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert offenders == []


def test_tdai_memory_exception_messages_use_i18n():
    offenders = []
    for path, tree in _iter_tdai_memory_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue
            exc = node.exc
            if not isinstance(exc, ast.Call) or not exc.args:
                continue
            message_arg = exc.args[0]
            if isinstance(message_arg, (ast.Constant, ast.JoinedStr)):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert offenders == []
