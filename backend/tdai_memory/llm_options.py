from typing import Any


def tdai_memory_thinking_kwargs(model: str | None) -> dict[str, Any]:
    if model is None or not model.lower().startswith("qwen3.6"):
        return {}

    return {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}
