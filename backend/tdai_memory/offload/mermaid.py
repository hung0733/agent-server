import json
import logging
import openai

from backend.i18n import t
logger = logging.getLogger(__name__)


async def build_mermaid_flowchart(
    entries: list,
    task_name: str,
    llm_client: openai.AsyncOpenAI,
    config,
) -> str | None:
    system_prompt = (
        "You generate Mermaid flowcharts from offload entries. "
        "Output ONLY a Mermaid flowchart in ```mermaid ... ``` format. "
        "Use `flowchart TD` (top-down). "
        "Node IDs must follow the pattern `{prefix}-N{number}`, e.g. `A-N1`, `B-N2`. "
        "Include tool_call summaries as node labels using double-quoted strings with line breaks (`<br/>`). "
        "Nodes should flow in chronological order. "
        "Edges should connect sequentially and branch where tool calls depend on earlier results. "
        "Use subgraphs to group related actions. "
        "Keep the diagram concise and readable."
    )
    entries_json = json.dumps(entries, indent=2, ensure_ascii=False)
    user_prompt = (
        f"Task: {task_name}\n"
        f"Offload entries (chronological):\n{entries_json}\n\n"
        f"Generate a `flowchart TD` Mermaid diagram summarizing this execution flow."
    )

    try:
        response = await llm_client.chat.completions.create(
            model=config.llm.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            timeout=config.llm.timeout_ms / 1000.0,
        )
        content = response.choices[0].message.content.strip()

        if "```mermaid" in content:
            start = content.index("```mermaid") + len("```mermaid")
            end = content.index("```", start)
            mmd = content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            raw = content[start:end].strip()
            if raw.startswith("mermaid"):
                raw = raw[len("mermaid"):].strip()
            mmd = raw
        else:
            mmd = content

        return mmd.strip() or None
    except Exception:
        logger.warning(t("tdai_memory.offload.build_mermaid_flowchart_failed"), exc_info=True)
        return None
