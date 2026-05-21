from __future__ import annotations

import json
import logging

import openai

from backend.tdai_memory.config import MemoryConfig

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Summarize the tool call result concisely. Include:
1. What the tool did
2. Key findings/output
3. A replaceability score (0-10): how easy is it to replace this result with the summary?
   0 = summary perfectly captures everything, 10 = must read the full result

Return JSON: {"summary": "...", "score": N}"""

_MAX_RESULT_CHARS = 4000


async def summarize_tool_result(
    tool_name: str,
    tool_input: dict,
    result_text: str,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
) -> tuple[str, int]:
    truncated = result_text[:_MAX_RESULT_CHARS]
    user_prompt = json.dumps(
        {"tool_name": tool_name, "tool_input": tool_input, "result_text": truncated},
        ensure_ascii=False,
    )

    try:
        response = await llm_client.chat.completions.create(
            model=config.llm.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=config.llm.max_tokens,
            timeout=config.llm.timeout_ms / 1000,
        )
        content = response.choices[0].message.content or ""
    except Exception:
        logger.exception("LLM summarization failed for tool %s", tool_name)
        return f"Tool '{tool_name}' executed.", 10

    try:
        data = json.loads(content)
        summary = str(data.get("summary", f"Tool '{tool_name}' executed."))
        score = int(data.get("score", 5))
        score = max(0, min(10, score))
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("Failed to parse LLM summary response")
        return f"Tool '{tool_name}' executed.", 5

    return summary, score
