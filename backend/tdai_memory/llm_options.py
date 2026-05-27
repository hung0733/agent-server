from typing import Any


def tdai_memory_thinking_kwargs() -> dict[str, Any]:
    return {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}
