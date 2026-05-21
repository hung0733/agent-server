from __future__ import annotations

import json
import logging
import os

import openai

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.offload.manager import OffloadManager

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


def _estimate_context_tokens(context: list[dict]) -> int:
    total = 0
    for msg in context:
        total += _estimate_tokens(str(msg.get("content", "")))
    return total


async def compress_context(
    agent_id: str,
    session_key: str,
    current_context: list[dict],
    offload_manager: OffloadManager,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    target_tokens: int,
) -> list[dict]:
    current_tokens = _estimate_context_tokens(current_context)
    if current_tokens <= target_tokens:
        return current_context

    offload_dir = os.path.join(offload_manager.data_dir, agent_id, "offload")
    jsonl_path = os.path.join(offload_dir, "offload.jsonl")

    import asyncio

    def _load_entries() -> list[dict]:
        if not os.path.exists(jsonl_path):
            return []
        entries: list[dict] = []
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    entries_raw = await asyncio.to_thread(_load_entries)
    entry_map: dict[str, dict] = {e["tool_call_id"]: e for e in entries_raw}

    def _try_mild(ctx: list[dict]) -> list[dict]:
        compressed: list[dict] = []
        for msg in ctx:
            content = str(msg.get("content", ""))
            role = str(msg.get("role", ""))
            if role == "tool":
                tool_call_id = str(msg.get("tool_call_id", ""))
                e = entry_map.get(tool_call_id)
                if e and e.get("score", 10) <= 3:
                    compressed.append({
                        **msg,
                        "content": f"[Summary] {e['summary']}",
                    })
                else:
                    compressed.append(msg)
            else:
                compressed.append(msg)
        return compressed

    def _try_aggressive(ctx: list[dict]) -> list[dict]:
        compressed: list[dict] = []
        for msg in ctx:
            content = str(msg.get("content", ""))
            role = str(msg.get("role", ""))
            if role == "tool":
                tool_call_id = str(msg.get("tool_call_id", ""))
                e = entry_map.get(tool_call_id)
                if e:
                    compressed.append({
                        **msg,
                        "content": f"[Summary] {e['summary']}",
                    })
                else:
                    compressed.append({
                        **msg,
                        "content": content[:800],
                    })
            else:
                compressed.append(msg)
        return compressed

    def _try_emergency(ctx: list[dict]) -> list[dict]:
        tool_msgs = [m for m in ctx if str(m.get("role", "")) == "tool"]
        non_tool_msgs = [m for m in ctx if str(m.get("role", "")) != "tool"]

        keep = non_tool_msgs[-4:] if len(non_tool_msgs) >= 4 else non_tool_msgs

        mermaid_parts: list[str] = []
        for m in tool_msgs:
            tool_call_id = str(m.get("tool_call_id", ""))
            e = entry_map.get(tool_call_id)
            if e:
                mermaid_parts.append(f"- {e['tool_call']}: {e['summary'][:120]}")
            else:
                content = str(m.get("content", ""))
                mermaid_parts.append(f"- Tool call: {content[:120]}")

        if mermaid_parts:
            mermaid_block = {
                "role": "system",
                "content": "[Emergency context]\nTool call flow:\n" + "\n".join(mermaid_parts[-20:]),
            }
            return [mermaid_block] + keep

        return keep

    compressed = _try_mild(current_context)
    if _estimate_context_tokens(compressed) <= target_tokens:
        return compressed

    compressed = _try_aggressive(current_context)
    while _estimate_context_tokens(compressed) > target_tokens and len(compressed) > 4:
        compressed = compressed[2:]

    if _estimate_context_tokens(compressed) <= target_tokens:
        return compressed

    compressed = _try_emergency(current_context)
    return compressed
