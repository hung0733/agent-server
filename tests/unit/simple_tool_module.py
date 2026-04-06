from __future__ import annotations


async def successful_tool(value: str) -> str:
    return f"ok:{value}"


async def failing_tool(value: str) -> str:
    raise RuntimeError(f"boom:{value}")
