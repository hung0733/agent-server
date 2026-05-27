from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import openai

from backend.i18n import t
from ..config import MemoryConfig
from .summarizer import summarize_tool_result

logger = logging.getLogger(__name__)

_OFFLOAD_JSONL = "offload.jsonl"

_BATCH_SYSTEM_PROMPT = (
    "You are a batch tool output summarizer. Given multiple tool calls and their results, "
    "produce a concise summary and a replaceability score (0-10) for EACH tool call. "
    "The replaceability score indicates how well the summary captures the essential information: "
    "0 means the summary captures everything needed and the full result can be safely discarded; "
    "10 means the summary is insufficient and the full result must be read.\n\n"
    "Output ONLY a JSON array of objects, one per tool call:\n"
    '[{"summary": "<concise summary>", "score": <integer 0-10>}, ...]'
)


async def _summarize_batch(
    pairs: list[tuple[str, str, dict, str]],
    llm_client: openai.AsyncOpenAI,
    config,
    conversation_messages: list[dict] | None = None,
) -> list[tuple[str, int]]:
    prompt_parts = []
    if conversation_messages:
        prompt_parts.append("## 对话上下文")
        for msg in conversation_messages[-5:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                prompt_parts.append(f"[user]: {content}")
            elif role == "assistant":
                prompt_parts.append(f"[assistant]: {content}")
        prompt_parts.append("")

    prompt_parts.append("## 工具调用批次")
    for i, (tc_id, tool_name, tool_input, result_text) in enumerate(pairs):
        truncated = result_text[:3000]
        prompt_parts.append(f"---")
        prompt_parts.append(f"Pair {i + 1}:")
        prompt_parts.append(f"Tool: {tool_name}")
        prompt_parts.append(f"Arguments: {json.dumps(tool_input)}")
        prompt_parts.append(f"Result:\n{truncated}")

    user_prompt = "\n".join(prompt_parts)

    response = await llm_client.chat.completions.create(
        model=config.llm.model,
        messages=[
            {"role": "system", "content": _BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        timeout=config.llm.timeout_ms / 1000.0,
    )
    content = response.choices[0].message.content.strip()
    parsed = _parse_batch_summary_content(content)
    results: list[tuple[str, int]] = []
    for item in parsed:
        if isinstance(item, str):
            summary = item
            score = 10
        elif isinstance(item, dict):
            summary = str(item.get("summary", ""))
            score = min(max(int(item.get("score", 10)), 0), 10)
        else:
            raise ValueError(t("tdai_memory.offload.invalid_batch_summary_response"))
        results.append((summary, score))
    return results


def _parse_batch_summary_content(content: str) -> list:
    parsed = json.loads(content)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return [parsed]
    if isinstance(parsed, dict):
        for key in ("results", "summaries", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    if isinstance(parsed, list):
        return parsed
    raise ValueError(t("tdai_memory.offload.invalid_batch_summary_response"))


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
    round_index: int = 0
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
        self._pending_count: int = 0
        self._flush_task: asyncio.Task | None = None
        self._pending_messages: list[dict] | None = None

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
        self, data_dir: str, llm_client: openai.AsyncOpenAI, config: MemoryConfig,
        pg_store: Any = None,
    ) -> None:
        self.data_dir = data_dir
        self.llm_client = llm_client
        self.config = config
        self._registry = SessionRegistry()
        self._pg_store = pg_store

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
        self,
        agent_id: str,
        session_key: str,
        tool_call_id: str,
        result_text: str,
        conversation_messages: list[dict] | None = None,
        round_index: int = 0,
        timestamp:int = 0
    ) -> None:
        state = await self._registry.get_or_create(
            session_key, agent_id, self.data_dir
        )
        pending = state.get_pending_pairs()
        call_data = pending.get(tool_call_id)
        if call_data is None:
            logger.warning(
                t("tdai_memory.offload.pending_tool_call_missing"),
                tool_call_id,
                session_key,
            )
            return

        call_data["result_text"] = result_text
        if timestamp > 0:
            call_data["timestamp"] = timestamp
        if round_index > 0:
            call_data["round_index"] = round_index
        if conversation_messages:
            state._pending_messages = conversation_messages
        state._pending_count += 1

        if state._pending_count >= 5:
            if state._flush_task and not state._flush_task.done():
                state._flush_task.cancel()
            await self._flush_pending(agent_id, session_key, state)
        else:
            if state._flush_task is None or state._flush_task.done():
                state._flush_task = asyncio.create_task(
                    self._flush_timer_task(agent_id, session_key, state)
                )

    async def _flush_timer_task(
        self, agent_id: str, session_key: str, state: OffloadStateManager
    ) -> None:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        await self._flush_pending(agent_id, session_key, state)

    async def _flush_pending(
        self, agent_id: str, session_key: str, state: OffloadStateManager
    ) -> None:
        async with state._l1_mutex:
            pending = state.get_pending_pairs()
            completed = {k: v for k, v in pending.items() if v.get("result_text", "")}
            if not completed:
                return

            conversation_msgs = state._pending_messages
            pairs = [
                (tc_id, v["tool_name"], v["tool_input"], v["result_text"])
                for tc_id, v in completed.items()
            ]

            results: list[tuple[str, int]] = []
            for attempt in range(3):
                try:
                    results = await _summarize_batch(
                        pairs, self.llm_client, self.config, conversation_msgs
                    )
                    break
                except Exception:
                    delay = 2 ** attempt
                    logger.warning(
                        t("tdai_memory.offload.batch_summarize_retry"),
                        attempt + 1,
                        delay,
                        exc_info=True,
                    )
                    if attempt < 2:
                        await asyncio.sleep(delay)
                    else:
                        results = [
                            (result_text[:200], 10)
                            for _, _, _, result_text in pairs
                        ]

            offload_dir = os.path.join(self.data_dir, agent_id, "offload")
            refs_dir = os.path.join(offload_dir, _REFS_DIR)
            jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)
            timestamp = datetime.now(timezone.utc).isoformat()

            for (tc_id, tool_name, tool_input, result_text), (summary, score) in zip(pairs, results):
                ref_filename = f"{tc_id}.md"
                ref_path = os.path.join(refs_dir, ref_filename)
                entry_data = completed.get(tc_id, {})
                entry_round_index = entry_data.get("round_index", 0)
                entry_timestamp_epoch = entry_data.get("timestamp", 0)
                if entry_timestamp_epoch > 0:
                    entry_timestamp_iso = datetime.fromtimestamp(entry_timestamp_epoch / 1000.0, tz=timezone.utc).isoformat()
                else:
                    entry_timestamp_iso = timestamp
                entry = OffloadEntry(
                    timestamp=entry_timestamp_iso,
                    node_id=None,
                    tool_call=summary[:80] if summary else tool_name,
                    summary=summary,
                    result_ref=os.path.join(_REFS_DIR, ref_filename),
                    tool_call_id=tc_id,
                    session_key=session_key,
                    round_index=entry_round_index,
                    score=score,
                )

                def _write(ep=ref_path, rfn=ref_filename, tn=tool_name, rt=result_text, ent=entry, jp=jsonl_path):
                    with open(ep, "w") as f:
                        f.write(f"# Tool: {tn}\n\n{rt}")
                    with open(jp, "a") as f:
                        f.write(json.dumps(ent.__dict__, ensure_ascii=False) + "\n")

                await asyncio.to_thread(_write)
                state.mark_processed(tc_id)

            if self._pg_store is not None:
                from backend.tdai_memory.models import L0Record
                for (tc_id, tool_name, tool_input, result_text), (summary, score) in zip(pairs, results):
                    pg_entry_data = completed.get(tc_id, {})
                    pg_timestamp_epoch = pg_entry_data.get("timestamp", 0)
                    pg_iso = timestamp
                    if pg_timestamp_epoch > 0:
                        pg_iso = datetime.fromtimestamp(pg_timestamp_epoch / 1000.0, tz=timezone.utc).isoformat()
                    tool_id = f"l0_tool_{tc_id}"
                    try:
                        await self._pg_store.upsert_l0(L0Record(
                            id=tool_id,
                            agent_id=agent_id,
                            session_key=session_key,
                            role="tool",
                            message_text=summary or result_text,
                            recorded_at=pg_iso,
                            timestamp=pg_timestamp_epoch or int(datetime.fromisoformat(pg_iso).timestamp() * 1000),
                        ))
                    except Exception:
                        pass

            for tc_id in completed:
                pending.pop(tc_id, None)
            state._pending_count = 0
            state._pending_messages = None
            state._flush_task = None

    async def get_offload_entries(
        self,
        agent_id: str,
        session_key: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

        def _read():
            if not os.path.exists(jsonl_path):
                return []
            entries: list[dict] = []
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if session_key is None or entry.get("session_key") == session_key:
                        entries.append(entry)
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return entries[:limit]

        return await asyncio.to_thread(_read)

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

    async def judge_task_boundary(
        self, agent_id: str, session_key: str, recent_messages: list[dict]
    ) -> dict:
        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

        def _read():
            if not os.path.exists(jsonl_path):
                return []
            entries = []
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            return entries[-20:]

        recent_entries = await asyncio.to_thread(_read)

        system_prompt = (
            "Given these recent messages and offload entries, determine if the current task "
            "is completed, continuing, or starting a new task. "
            "Output ONLY a JSON object with no extra text:\n"
            '{"status": "completed"|"continuing"|"new_task", "reason": "..."}'
        )

        user_data = {
            "messages": recent_messages,
            "recent_tool_executions": recent_entries,
        }
        user_prompt = json.dumps(user_data, ensure_ascii=False, indent=2)

        try:
            response = await self.llm_client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                timeout=self.config.llm.timeout_ms / 1000.0,
            )
            content = response.choices[0].message.content.strip()
            result = json.loads(content)
        except Exception:
            logger.warning(t("tdai_memory.offload.task_boundary_judge_failed"), exc_info=True)
            return {"status": "continuing", "reason": "error"}

        status = result.get("status", "continuing")
        if status in ("completed", "new_task"):
            state = await self._registry.resolve_if_allowed(session_key)
            if state:
                state.mmd_counter += 1
                state.active_mmd_id = f"mmd_{state.mmd_counter}"
                state.active_mmd_file = f"{state.active_mmd_id}.mmd"
                state._l15_boundaries.append(datetime.now(timezone.utc).isoformat())
                await asyncio.to_thread(state.save_state, agent_id, self.data_dir)

        return result

    async def create_skill(
        self, agent_id: str, mmd_name: str, focus: str = ""
    ) -> str | None:
        import re

        offload_dir = os.path.join(self.data_dir, agent_id, "offload")
        mmd_path = os.path.join(offload_dir, _MMDS_DIR, f"{mmd_name}.mmd")

        def _read_mmd():
            if not os.path.exists(mmd_path):
                return None
            with open(mmd_path, "r") as f:
                return f.read()

        mmd_content = await asyncio.to_thread(_read_mmd)
        if not mmd_content:
            logger.warning(t("tdai_memory.offload.mmd_not_found"), mmd_name)
            return None

        node_ids = re.findall(r"\bN\d+\b", mmd_content)
        if not node_ids:
            return None

        jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

        def _read_offload():
            if not os.path.exists(jsonl_path):
                return []
            entries = []
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            return entries

        all_entries = await asyncio.to_thread(_read_offload)
        filtered = [e for e in all_entries if e.get("node_id") in node_ids]
        if not filtered:
            return None

        system_prompt = (
            "Generate a reusable skill from these tool interactions. "
            "A skill is a reusable pattern that can be applied to similar situations. "
            "Include the tool calls, their purpose, parameters, and how to interpret results. "
            "Format as a SKILL.md file with clear sections: purpose, prerequisites, steps, and examples."
        )
        entries_json = json.dumps(filtered, ensure_ascii=False, indent=2)
        focus_hint = f"\nFocus area: {focus}" if focus else ""
        user_prompt = f"Tool interactions:{focus_hint}\n{entries_json}"

        try:
            response = await self.llm_client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                timeout=self.config.llm.timeout_ms / 1000.0,
            )
            skill_content = response.choices[0].message.content
        except Exception:
            logger.warning(t("tdai_memory.offload.skill_generation_failed"), mmd_name, exc_info=True)
            return None

        skill_name = mmd_name
        skill_dir = os.path.join(self.data_dir, agent_id, "offload", "skills", skill_name)
        skill_path = os.path.join(skill_dir, "SKILL.md")

        def _write_skill():
            os.makedirs(skill_dir, exist_ok=True)
            with open(skill_path, "w") as f:
                f.write(skill_content)

        await asyncio.to_thread(_write_skill)

        logger.info(t("tdai_memory.offload.skill_created"), skill_name, agent_id)
        return skill_content

    def on_before_tool_call(
        self, agent_id: str, session_key: str, tool_call_id: str,
        tool_name: str, tool_input: dict,
    ) -> None:
        self.record_tool_call(agent_id, session_key, tool_call_id, tool_name, tool_input)

    async def on_after_tool_call(
        self, agent_id: str, session_key: str, tool_call_id: str,
        result_text: str, conversation_messages: list[dict] | None = None,
    ) -> None:
        await self.record_tool_result(
            agent_id, session_key, tool_call_id, result_text, conversation_messages
        )

    async def on_before_prompt_build(
        self, agent_id: str, session_key: str,
        current_messages: list[dict], target_tokens: int | None = None,
    ) -> list[dict]:
        state = await self._registry.resolve_if_allowed(session_key)
        if state:
            pending = state.get_pending_pairs()
            if pending:
                has_completed = any(
                    v.get("result_text", "") for v in pending.values()
                )
                if has_completed:
                    await self._flush_pending(agent_id, session_key, state)
        if target_tokens:
            return await self.compress_context(
                agent_id, session_key, current_messages, target_tokens
            )
        return current_messages
