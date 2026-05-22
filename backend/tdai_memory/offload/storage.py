from __future__ import annotations

import asyncio
import json
import logging
import os

from backend.i18n import t
logger = logging.getLogger(__name__)

_OFFLOAD_JSONL = "offload.jsonl"
_MMDS_DIR = "mmds"
_STATE_FILE = "state.json"


async def read_offload_entries(
    agent_id: str, data_dir: str, session_key: str | None = None, limit: int = 100
) -> list[dict]:
    """Read offload entries from offload.jsonl with optional session filter."""
    jsonl_path = os.path.join(data_dir, agent_id, "offload", _OFFLOAD_JSONL)

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
                    if session_key is None or entry.get("session_key") == session_key:
                        entries.append(entry)
                except json.JSONDecodeError:
                    logger.warning(t("tdai_memory.offload.skipping_malformed_jsonl_line"))
                    continue

        if limit > 0 and len(entries) > limit:
            entries = entries[-limit:]

        return entries

    return await asyncio.to_thread(_read)


async def write_offload_entry(agent_id: str, data_dir: str, entry: dict) -> None:
    """Append a single offload entry to offload.jsonl."""
    offload_dir = os.path.join(data_dir, agent_id, "offload")
    jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

    def _write():
        os.makedirs(offload_dir, exist_ok=True)
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    await asyncio.to_thread(_write)


async def read_state_file(agent_id: str, data_dir: str) -> dict | None:
    """Read persistent state.json for offload."""
    state_path = os.path.join(data_dir, agent_id, "offload", _STATE_FILE)

    def _read():
        if not os.path.exists(state_path):
            return None
        with open(state_path, "r") as f:
            return json.load(f)

    return await asyncio.to_thread(_read)


async def write_state_file(agent_id: str, data_dir: str, state: dict) -> None:
    """Write persistent state.json for offload."""
    offload_dir = os.path.join(data_dir, agent_id, "offload")
    state_path = os.path.join(offload_dir, _STATE_FILE)

    def _write():
        os.makedirs(offload_dir, exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)


async def read_mmd_file(agent_id: str, data_dir: str, filename: str) -> str | None:
    """Read a Mermaid .mmd file."""
    mmd_path = os.path.join(data_dir, agent_id, "offload", _MMDS_DIR, filename)

    def _read():
        if not os.path.exists(mmd_path):
            return None
        with open(mmd_path, "r") as f:
            return f.read()

    return await asyncio.to_thread(_read)


async def write_mmd_file(agent_id: str, data_dir: str, filename: str, content: str) -> None:
    """Write a Mermaid .mmd file."""
    mmds_dir = os.path.join(data_dir, agent_id, "offload", _MMDS_DIR)
    mmd_path = os.path.join(mmds_dir, filename)

    def _write():
        os.makedirs(mmds_dir, exist_ok=True)
        with open(mmd_path, "w") as f:
            f.write(content)

    await asyncio.to_thread(_write)


def parse_session_key(session_key: str) -> dict:
    """Parse session key format 'agent:name:id' into components."""
    parts = session_key.split(":")
    if len(parts) >= 3:
        return {
            "agent": parts[0],
            "name": parts[1],
            "id": ":".join(parts[2:]),
        }
    if len(parts) == 2:
        return {
            "agent": parts[0],
            "name": parts[1],
            "id": "",
        }
    return {
        "agent": session_key,
        "name": "",
        "id": "",
    }
