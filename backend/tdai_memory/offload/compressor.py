import json
import logging
import openai

logger = logging.getLogger(__name__)


async def compress_context(
    agent_id: str,
    session_key: str,
    current_context: list[dict],
    offload_manager,
    llm_client: openai.AsyncOpenAI,
    config,
    target_tokens: int,
) -> list[dict]:
    result = _try_mild(current_context, offload_manager)
    if _estimate_tokens(result) <= target_tokens:
        return result

    result = await _try_aggressive(result, offload_manager, llm_client, config, target_tokens)
    if _estimate_tokens(result) <= target_tokens:
        return result

    result = await _try_emergency(result, offload_manager, target_tokens)
    return result


def _estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) // 2
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    total += len(block["text"]) // 2
    return total


def _try_mild(context: list[dict], offload_manager) -> list[dict]:
    threshold = int(len(context) * 0.3)
    tail = context[threshold:]

    for msg in tail:
        if msg.get("role") != "tool":
            continue
        entries = offload_manager.get_entries_for_message(msg)
        if not entries:
            continue
        low_score_entries = [e for e in entries if e.get("replaceability_score", 10) <= 3]
        if not low_score_entries:
            continue
        summaries = [e["summary"] for e in low_score_entries]
        combined = " | ".join(summaries)
        msg["content"] = f"[Summary: {combined}]"

    return context


async def _try_aggressive(
    context: list[dict],
    offload_manager,
    llm_client,
    config,
    target_tokens: int,
) -> list[dict]:
    from .summarizer import summarize_tool_result

    for msg in context:
        if msg.get("role") != "tool":
            continue
        entries = offload_manager.get_entries_for_message(msg)
        if entries:
            best_entry = _pick_best_entry(entries)
            msg["content"] = f"[Summary: {best_entry['summary']}]"
        else:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 800:
                msg["content"] = content[:800] + "..."

    i = 0
    while i < len(context) and _estimate_tokens(context) > target_tokens:
        msg = context[i]
        role = msg.get("role", "")
        if role == "tool":
            if i + 1 < len(context) and context[i + 1].get("role") == "user":
                del context[i : i + 2]
                continue
            del context[i]
            continue
        if role == "user" and i + 1 < len(context):
            del context[i]
            continue
        if role == "assistant":
            del context[i]
            continue
        i += 1

    return context


async def _try_emergency(
    context: list[dict],
    offload_manager,
    target_tokens: int,
) -> list[dict]:
    non_tool = [msg for msg in context if msg.get("role") != "tool"]
    tool_msgs = [msg for msg in context if msg.get("role") == "tool"]

    if len(non_tool) > 4:
        non_tool = non_tool[-4:]

    tool_summaries = []
    for msg in tool_msgs:
        entries = offload_manager.get_entries_for_message(msg)
        if entries:
            e = _pick_best_entry(entries)
            tool_summaries.append(f"- {e.get('call_id', '?'):>6}: {e['summary']}")
        else:
            content = msg.get("content", "")
            if isinstance(content, str):
                tool_summaries.append(f"- ???: {content[:120]}")

    if tool_summaries:
        flow_block = {
            "role": "user",
            "content": "<tool-flow-summary>\n" + "\n".join(tool_summaries) + "\n</tool-flow-summary>",
        }
        non_tool.insert(-1, flow_block)

    return non_tool


def _pick_best_entry(entries: list) -> dict:
    best = entries[0]
    best_score = best.get("replaceability_score", 10)
    for e in entries[1:]:
        score = e.get("replaceability_score", 10)
        if score < best_score:
            best = e
            best_score = score
    return best
