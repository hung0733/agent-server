import ast
from pathlib import Path

from backend.tdai_memory.llm_options import tdai_memory_thinking_kwargs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TDAI_MEMORY_DIR = PROJECT_ROOT / "backend" / "tdai_memory"


def test_tdai_memory_thinking_kwargs_enables_thinking():
    assert tdai_memory_thinking_kwargs() == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}}
    }


def test_tdai_memory_chat_completion_calls_enable_thinking():
    offenders = []
    for path in TDAI_MEMORY_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_chat_completions_create(node.func):
                continue
            if not _has_thinking_kwargs(node):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert offenders == []


def _is_chat_completions_create(node: ast.AST) -> bool:
    return ".".join(_attribute_parts(node)).endswith("chat.completions.create")


def _attribute_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Attribute):
        return [*_attribute_parts(node.value), node.attr]
    if isinstance(node, ast.Name):
        return [node.id]
    return []


def _has_thinking_kwargs(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg is not None:
            continue
        value = keyword.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id == "tdai_memory_thinking_kwargs":
                return True
    return False
