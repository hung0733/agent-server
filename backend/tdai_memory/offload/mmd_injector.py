from __future__ import annotations

import asyncio
import logging
import os

import openai

from backend.i18n import t
logger = logging.getLogger(__name__)


async def inject_active_mmd(context: list[dict], mmd_text: str, task_name: str) -> list[dict]:
    """Inject active task MMD into context messages. Adds an MMD section after system message."""
    if not mmd_text:
        return context

    mmd_block = {
        "role": "system",
        "content": (
            f"<task-mermaid name=\"{task_name}\">\n"
            f"```mermaid\n{mmd_text}\n```\n"
            f"</task-mermaid>"
        ),
    }

    for i, msg in enumerate(context):
        if msg.get("role") == "system":
            result = context[:i + 1] + [mmd_block] + context[i + 1:]
            return result

    return [mmd_block] + context


async def inject_history_mmd(
    context: list[dict], mmd_files: list[str], data_dir: str, agent_id: str
) -> list[dict]:
    """Read historical MMD files and inject summarized versions into context."""
    if not mmd_files:
        return context

    mmds_dir = os.path.join(data_dir, agent_id, "offload", "mmds")
    summaries: list[str] = []

    def _read():
        texts = []
        for fname in mmd_files[-5:]:
            path = os.path.join(mmds_dir, fname)
            if not os.path.exists(path):
                continue
            with open(path, "r") as f:
                text = f.read()
            texts.append((fname, text))
        return texts

    file_texts = await asyncio.to_thread(_read)
    if not file_texts:
        return context

    for fname, text in file_texts:
        summary = " ".join(text.split())[:300]
        summaries.append(f"- [{fname}]: {summary}")

    history_block = {
        "role": "system",
        "content": (
            "<history-mermaid-summaries>\n"
            + "\n".join(summaries)
            + "\n</history-mermaid-summaries>"
        ),
    }

    for i, msg in enumerate(context):
        if msg.get("role") == "system":
            return context[:i + 1] + [history_block] + context[i + 1:]

    return [history_block] + context


async def generate_mmd_summary(
    mmd_text: str, llm_client: openai.AsyncOpenAI, config
) -> str:
    """Generate a brief summary of a Mermaid flowchart for context injection."""
    if not mmd_text:
        return ""

    system_prompt = (
        "Summarize the following Mermaid flowchart in 2-3 sentences. "
        "Describe the overall flow and key decision points. "
        "Output ONLY the summary text with no extra formatting."
    )

    try:
        response = await llm_client.chat.completions.create(
            model=config.llm.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"```mermaid\n{mmd_text}\n```"},
            ],
            temperature=0.0,
            timeout=config.llm.timeout_ms / 1000.0,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        logger.warning(t("tdai_memory.offload.generate_mmd_summary_failed"), exc_info=True)
        first_line = mmd_text.strip().split("\n")[0][:120]
        return f"Flowchart: {first_line}..."
