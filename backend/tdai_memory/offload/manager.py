from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import openai

from backend.i18n import t
from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.offload.summarizer import summarize_tool_result

logger = logging.getLogger(__name__)

@dataclass
class OffloadEntry:
    timestamp: str
    node_id: str | None
    tool_call: str
    summary: str
    result_ref: str
    tool_call_id: str
    session_key: str = ""
    score: int = 0


class OffloadManager:
    def __init__(self, data_dir: str, llm_client: openai.AsyncOpenAI, config: MemoryConfig):
        self.data_dir = data_dir
        self.llm_client = llm_client
        self.config = config
        self._buffer: dict[str, dict[str, dict[str, dict]]] = {}

    async def initialize(self, agent_id: str) -> None:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        refs_dir = os.path.join(offload_dir, self.config.offload.refs_dir)
        mmds_dir = os.path.join(offload_dir, self.config.offload.mmds_dir)

        def _ensure():
            os.makedirs(refs_dir, exist_ok=True)
            os.makedirs(mmds_dir, exist_ok=True)

        await asyncio.to_thread(_ensure)

    async def record_tool_call(
        self, agent_id: str, session_key: str, tool_call_id: str, tool_name: str, tool_input: dict
    ) -> None:
        key = (agent_id, session_key)
        if agent_id not in self._buffer:
            self._buffer[agent_id] = {}
        if session_key not in self._buffer[agent_id]:
            self._buffer[agent_id][session_key] = {}
        self._buffer[agent_id][session_key][tool_call_id] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "session_key": session_key,
        }

    async def record_tool_result(
        self, agent_id: str, session_key: str, tool_call_id: str, result_text: str
    ) -> None:
        call_data = (
            self._buffer.get(agent_id, {}).get(session_key, {}).pop(tool_call_id, None)
        )
        if call_data is None:
            logger.warning(
                t("tdai_memory.offload.pending_tool_call_missing"),
                tool_call_id, session_key,
            )
            return

        tool_name = call_data["tool_name"]
        tool_input = call_data["tool_input"]

        summary, score = await summarize_tool_result(
            tool_name, tool_input, result_text, self.llm_client, self.config
        )

        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        refs_dir = os.path.join(offload_dir, self.config.offload.refs_dir)
        ref_filename = f"{tool_call_id}.md"
        ref_path = os.path.join(refs_dir, ref_filename)
        jsonl_path = os.path.join(offload_dir, self.config.offload.jsonl_filename)

        timestamp = datetime.now(timezone.utc).isoformat()
        entry = OffloadEntry(
            timestamp=timestamp,
            node_id=None,
            tool_call=(
                summary[: self.config.offload.tool_call_label_chars]
                if summary
                else tool_name
            ),
            summary=summary,
            result_ref=os.path.join(self.config.offload.refs_dir, ref_filename),
            tool_call_id=tool_call_id,
            session_key=session_key,
            score=score,
        )

        def _write():
            with open(ref_path, "w") as f:
                f.write(f"# Tool: {tool_name}\n\n{result_text}")
            with open(jsonl_path, "a") as f:
                f.write(json.dumps(entry.__dict__, ensure_ascii=False) + "\n")

        await asyncio.to_thread(_write)

    async def get_offload_context(
        self, agent_id: str, session_key: str = "", compression_level: str | None = None
    ) -> str:
        compression_level = compression_level or self.config.offload.default_compression_level
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        jsonl_path = os.path.join(offload_dir, self.config.offload.jsonl_filename)

        def _read():
            if not os.path.exists(jsonl_path):
                return []
            entries: list[dict] = []
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            return entries

        all_entries = await asyncio.to_thread(_read)
        if not all_entries:
            return ""

        if compression_level == "mild":
            recent = all_entries[-self.config.offload.mild_recent_entries :]
            lines = []
            for e in recent:
                if e.get("score", 10) <= self.config.offload.mild_inline_score_threshold:
                    lines.append(f"- {e['tool_call']}: {e['summary']}")
                else:
                    lines.append(f"- {e['tool_call']} (see {e['result_ref']})")
            return "[Tool execution summary]\n" + "\n".join(lines)

        if compression_level == "aggressive":
            lines = []
            for e in all_entries[-self.config.offload.aggressive_recent_entries :]:
                lines.append(f"- {e['tool_call']}: {e['summary']}")
            return "[Compressed tool execution summary]\n" + "\n".join(lines)

        if compression_level == "emergency":
            lines = ["[Critical: full context compressed]"]
            lines.append("Key tool calls:")
            for e in all_entries[-self.config.offload.emergency_recent_entries :]:
                lines.append(f"- {e['tool_call']} [{e['timestamp'][:19]}]")
            return "\n".join(lines)

        return ""

    async def build_mermaid(self, agent_id: str, task_name: str) -> str | None:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        jsonl_path = os.path.join(offload_dir, self.config.offload.jsonl_filename)

        def _read():
            if not os.path.exists(jsonl_path):
                return []
            entries: list[OffloadEntry] = []
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        entries.append(OffloadEntry(
                            timestamp=data.get("timestamp", ""),
                            node_id=data.get("node_id"),
                            tool_call=data.get("tool_call", ""),
                            summary=data.get("summary", ""),
                            result_ref=data.get("result_ref", ""),
                            tool_call_id=data.get("tool_call_id", ""),
                            session_key=data.get("session_key", ""),
                            score=data.get("score", 0),
                        ))
            return entries

        entries = await asyncio.to_thread(_read)
        if not entries:
            return None

        from backend.tdai_memory.offload.mermaid import build_mermaid_flowchart

        mmd = await build_mermaid_flowchart(entries, task_name, self.llm_client, self.config)
        if mmd:
            mmds_dir = os.path.join(offload_dir, self.config.offload.mmds_dir)
            mmd_path = os.path.join(mmds_dir, f"{task_name}.mmd")

            def _write():
                os.makedirs(mmds_dir, exist_ok=True)
                with open(mmd_path, "w") as f:
                    f.write(mmd)

            await asyncio.to_thread(_write)

        return mmd
