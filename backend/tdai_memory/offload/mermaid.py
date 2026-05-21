from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import openai

from backend.i18n import t
from backend.tdai_memory.config import MemoryConfig

if TYPE_CHECKING:
    from backend.tdai_memory.offload.manager import OffloadEntry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a Mermaid flowchart generator. Given a list of tool calls and their summaries,
generate a Mermaid JS flowchart (flowchart TD format) that shows the sequence and relationships of tool calls.

Rules:
- Each tool call should be a node
- Nodes should show a short label (tool name + brief summary)
- Connect nodes with arrows showing the flow
- Use subgraphs to group related tool calls if applicable
- Output ONLY the Mermaid diagram code, nothing else
- The graph should be readable and well-organized

Example output format:
```mermaid
flowchart TD
    A[Tool A: Did something]
    B[Tool B: Did something else]
    C[Tool C: Combined results]
    A --> B
    B --> C
```"""


async def build_mermaid_flowchart(
    entries: list[OffloadEntry],
    task_name: str,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
) -> str | None:
    if not entries:
        return None

    entry_lines = []
    for i, e in enumerate(entries):
        entry_lines.append(
            f"{i + 1}. [{e.timestamp[:19]}] {e.tool_call} "
            f"(score={e.score}): {e.summary[: config.offload.mermaid_entry_summary_chars]}"
        )
    entry_text = "\n".join(entry_lines)

    user_prompt = f"Task: {task_name}\n\nTool calls:\n{entry_text}"

    try:
        response = await llm_client.chat.completions.create(
            model=config.llm.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=config.llm.max_tokens,
            timeout=config.llm.timeout_ms / 1000,
        )
        content = response.choices[0].message.content or ""
    except Exception:
        logger.exception(t("tdai_memory.offload.mermaid_failed"), task_name)
        return None

    content = content.strip()
    if not content:
        return None

    if "```" in content:
        lines = content.split("\n")
        cleaned: list[str] = []
        in_block = False
        for line in lines:
            if line.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                cleaned.append(line)
        if cleaned:
            content = "\n".join(cleaned).strip()

    if not content.startswith("flowchart") and not content.startswith("graph"):
        return None

    return content
