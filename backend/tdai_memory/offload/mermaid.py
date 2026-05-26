import asyncio
import json
import logging
import os
import re
import openai

from backend.i18n import t
logger = logging.getLogger(__name__)

_NODE_ID_RE = re.compile(r"\bN\d+\b")


async def build_mermaid_flowchart(
    entries: list,
    task_name: str,
    llm_client: openai.AsyncOpenAI,
    config,
    replace_blocks: list[dict] | None = None,
) -> str | None:
    if replace_blocks:
        system_prompt = (
            "You update specific nodes in a Mermaid flowchart. "
            "Given the current flowchart and a list of nodes to update, "
            "only regenerate those specific node blocks while preserving all other nodes unchanged. "
            "Output ONLY the full updated Mermaid flowchart in ```mermaid ... ``` format. "
            "Use `flowchart TD` (top-down). "
            "Node IDs must follow the pattern `{prefix}-N{number}`, e.g. `A-N1`, `B-N2`. "
            "Include tool_call summaries as node labels using double-quoted strings with line breaks (`<br/>`). "
            "Keep the diagram concise and readable."
        )
        replace_json = json.dumps(replace_blocks, ensure_ascii=False)
        entries_json = json.dumps(entries, indent=2, ensure_ascii=False)
        user_prompt = (
            f"Task: {task_name}\n"
            f"Current entries to update:\n{entries_json}\n\n"
            f"Nodes to replace (keep existing structure for other nodes):\n{replace_json}\n\n"
            f"Generate the updated `flowchart TD` Mermaid diagram."
        )
    else:
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

        node_mapping = {}
        for match in _NODE_ID_RE.finditer(mmd):
            node_mapping[match.group(0)] = True

        return mmd.strip() or None
    except Exception:
        logger.warning(t("tdai_memory.offload.build_mermaid_flowchart_failed"), exc_info=True)
        return None


async def node_id_backfill(
    entries: list[dict],
    node_mapping: dict[str, str],
    storage_dir: str,
    agent_id: str,
) -> None:
    offload_dir = os.path.join(storage_dir, agent_id, "offload")
    jsonl_path = os.path.join(offload_dir, "offload.jsonl")

    def _backfill():
        if not os.path.exists(jsonl_path):
            return
        lines = []
        with open(jsonl_path, "r") as f:
            for line in f:
                line_stripped = line.strip()
                if not line_stripped:
                    lines.append(line)
                    continue
                entry = json.loads(line_stripped)
                entry_id = entry.get("tool_call_id", "")
                if entry_id in node_mapping:
                    entry["node_id"] = node_mapping[entry_id]
                lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
        with open(jsonl_path, "w") as f:
            f.writelines(lines)

    await asyncio.to_thread(_backfill)
    logger.info(t("tdai_memory.offload.node_id_backfill_done"), agent_id, len(node_mapping))
