from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import openai

from tdai_memory.config import MemoryConfig
from .summarizer import summarize_tool_result

logger = logging.getLogger(__name__)

_OFFLOAD_JSONL = "offload.jsonl"
_REFS_DIR = "refs"
_MMDS_DIR = "mmds"
_STATE_FILE = "state.json"
_MAX_SESSIONS = 20
_SESSION_TTL_MS = 30 * 60 * 1000


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


class OffloadStateManager:
    def __init__(self) -> None:
        self.active_mmd_file: str = ""
        self.active_mmd_id: str = ""
        self.mmd_counter: int = 0
        self.last_session_key: str = ""
        self.last_offloaded_tool_call_id: str = ""
        self.last_l2_trigger_time: str = ""
        self._pending_tool_pairs: dict[str, dict] = {}
        self._processed_tool_call_ids: set[str] = set()
        self._l1_mutex = asyncio.Lock()
        self._l15_boundaries: list[str] = []
        self._confirmed_offload_ids: set[str] = set()
        self._deleted_offload_ids: set[str] = set()
        self._consecutive_null_count: int = 0

    def load_state(self, agent_id: str, data_dir: str) -> None:
        state_path = os.path.join(data_dir, agent_id, "offload", _STATE_FILE)
        if not os.path.exists(state_path):
            return
        with open(state_path, "r") as f:
            data = json.load(f)
        self.active_mmd_file = data.get("active_mmd_file", "")
        self.active_mmd_id = data.get("active_mmd_id", "")
        self.mmd_counter = data.get("mmd_counter", 0)
        self.last_session_key = data.get("last_session_key", "")
        self.last_offloaded_tool_call_id = data.get("last_offloaded_tool_call_id", "")
        self.last_l2_trigger_time = data.get("last_l2_trigger_time", "")

    def save_state(self, agent_id: str, data_dir: str) -> None:
        state_path = os.path.join(data_dir, agent_id, "offload", _STATE_FILE)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        data = {
            "active_mmd_file": self.active_mmd_file,
            "active_mmd_id": self.active_mmd_id,
            "mmd_counter": self.mmd_counter,
            "last_session_key": self.last_session_key,
            "last_offloaded_tool_call_id": self.last_offloaded_tool_call_id,
            "last_l2_trigger_time": self.last_l2_trigger_time,
        }
        with open(state_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_tool_pair(
        self, tool_call_id: str, tool_name: str, tool_input: dict, result_text: str
    ) -> None:
        self._pending_tool_pairs[tool_call_id] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "result_text": result_text,
        }

    def get_pending_pairs(self) -> dict[str, dict]:
        return self._pending_tool_pairs

    def clear_pending_pairs(self) -> None:
        self._pending_tool_pairs.clear()

    def mark_processed(self, tool_call_id: str) -> None:
        self._processed_tool_call_ids.add(tool_call_id)

    def is_processed(self, tool_call_id: str) -> bool:
        return tool_call_id in self._processed_tool_call_ids

    def get_null_count(self) -> int:
        return self._consecutive_null_count

    def increment_null_count(self) -> None:
        self._consecutive_null_count += 1

    def reset_null_count(self) -> None:
        self._consecutive_null_count = 0


@dataclass
class _SessionCtx:
    state: OffloadStateManager
    last_access_ms: int


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _SessionCtx] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self, session_key: str, agent_id: str, data_dir: str
    ) -> OffloadStateManager:
        async with self._lock:
            now_ms = int(time.time() * 1000)
            ctx = self._sessions.get(session_key)
            if ctx is not None:
                ctx.last_access_ms = now_ms
                return ctx.state
            if len(self._sessions) >= _MAX_SESSIONS:
                oldest_key = min(
                    self._sessions, key=lambda k: self._sessions[k].last_access_ms
                )
                del self._sessions[oldest_key]
            state = OffloadStateManager()
            await asyncio.to_thread(state.load_state, agent_id, data_dir)
            self._sessions[session_key] = _SessionCtx(
                state=state, last_access_ms=now_ms
            )
            return state

    async def resolve_if_allowed(self, session_key: str) -> OffloadStateManager | None:
        async with self._lock:
            ctx = self._sessions.get(session_key)
            if ctx is None:
                return None
            if session_key.startswith("memory-pipeline"):
                return None
            ctx.last_access_ms = int(time.time() * 1000)
            return ctx.state

    async def gc_stale(self) -> None:
        async with self._lock:
            now_ms = int(time.time() * 1000)
            stale = [
                key
                for key, ctx in self._sessions.items()
                if now_ms - ctx.last_access_ms > _SESSION_TTL_MS
            ]
            for key in stale:
                del self._sessions[key]


class OffloadManager:
    def __init__(
        self, data_dir: str, llm_client: openai.AsyncOpenAI, config: MemoryConfig
    ) -> None:
        self.data_dir = data_dir
        self.llm_client = llm_client
        self.config = config
        self._registry = SessionRegistry()

    async def initialize(self, agent_id: str) -> None:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        refs_dir = os.path.join(offload_dir, _REFS_DIR)
        mmds_dir = os.path.join(offload_dir, _MMDS_DIR)

        def _ensure():
            os.makedirs(refs_dir, exist_ok=True)
            os.makedirs(mmds_dir, exist_ok=True)

        await asyncio.to_thread(_ensure)

    async def record_tool_call(
        self,
        agent_id: str,
        session_key: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
    ) -> None:
        state = await self._registry.get_or_create(
            session_key, agent_id, self.data_dir
        )
        state.add_tool_pair(tool_call_id, tool_name, tool_input, "")

    async def record_tool_result(
        self, agent_id: str, session_key: str, tool_call_id: str, result_text: str
    ) -> None:
        state = await self._registry.get_or_create(
            session_key, agent_id, self.data_dir
        )
        pending = state.get_pending_pairs()
        call_data = pending.pop(tool_call_id, None)
        if call_data is None:
            logger.warning(
                "No pending tool call found for tool_call_id=%s session=%s",
                tool_call_id,
                session_key,
            )
            return

        tool_name = call_data["tool_name"]
        tool_input = call_data["tool_input"]

        summary, score = await summarize_tool_result(
            tool_name, tool_input, result_text, self.llm_client, self.config
        )

        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        refs_dir = os.path.join(offload_dir, _REFS_DIR)
        ref_filename = f"{tool_call_id}.md"
        ref_path = os.path.join(refs_dir, ref_filename)
        jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

        timestamp = datetime.now(timezone.utc).isoformat()
        entry = OffloadEntry(
            timestamp=timestamp,
            node_id=None,
            tool_call=summary[:80] if summary else tool_name,
            summary=summary,
            result_ref=os.path.join(_REFS_DIR, ref_filename),
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
        state.mark_processed(tool_call_id)

    async def get_offload_context(
        self, agent_id: str, session_key: str = "", compression_level: str = "mild"
    ) -> str:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

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
            recent = all_entries[-10:]
            lines = []
            for e in recent:
                if e.get("score", 10) <= 3:
                    lines.append(f"- {e['tool_call']}: {e['summary']}")
                else:
                    lines.append(f"- {e['tool_call']} (see {e['result_ref']})")
            return "[Tool execution summary]\n" + "\n".join(lines)

        if compression_level == "aggressive":
            lines = []
            for e in all_entries[-15:]:
                lines.append(f"- {e['tool_call']}: {e['summary']}")
            return "[Compressed tool execution summary]\n" + "\n".join(lines)

        if compression_level == "emergency":
            lines = ["[Critical: full context compressed]"]
            lines.append("Key tool calls:")
            for e in all_entries[-20:]:
                lines.append(f"- {e['tool_call']} [{e['timestamp'][:19]}]")
            return "\n".join(lines)

        return ""

    async def build_mermaid(self, agent_id: str, task_name: str) -> str | None:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

        def _read():
            if not os.path.exists(jsonl_path):
                return []
            entries: list[OffloadEntry] = []
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        entries.append(
                            OffloadEntry(
                                timestamp=data.get("timestamp", ""),
                                node_id=data.get("node_id"),
                                tool_call=data.get("tool_call", ""),
                                summary=data.get("summary", ""),
                                result_ref=data.get("result_ref", ""),
                                tool_call_id=data.get("tool_call_id", ""),
                                session_key=data.get("session_key", ""),
                                score=data.get("score", 0),
                            )
                        )
            return entries

        entries = await asyncio.to_thread(_read)
        if not entries:
            return None

        from .mermaid import build_mermaid_flowchart

        mmd = await build_mermaid_flowchart(
            entries, task_name, self.llm_client, self.config
        )
        if mmd:
            mmds_dir = os.path.join(offload_dir, _MMDS_DIR)
            mmd_path = os.path.join(mmds_dir, f"{task_name}.mmd")

            def _write():
                os.makedirs(mmds_dir, exist_ok=True)
                with open(mmd_path, "w") as f:
                    f.write(mmd)

            await asyncio.to_thread(_write)

        return mmd

    async def compress_context(
        self,
        agent_id: str,
        session_key: str,
        current_context: list[dict],
        target_tokens: int,
    ) -> list[dict]:
        from .compressor import compress_context as _compress

        return await _compress(
            agent_id,
            session_key,
            current_context,
            self,
            self.llm_client,
            self.config,
            target_tokens,
        )
