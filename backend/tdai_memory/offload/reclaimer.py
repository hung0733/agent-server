from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_OFFLOAD_JSONL = "offload.jsonl"
_REFS_DIR = "refs"
_MMDS_DIR = "mmds"


async def reclaim_offload_data(agent_id: str, data_dir: str, retention_days: int = 7) -> dict:
    """Clean up expired offload data: JSONL entries, refs, MMDs, logs."""
    expired_count = await clean_expired_entries(agent_id, data_dir, retention_days)
    orphan_count = await clean_orphan_refs(agent_id, data_dir)
    mmd_count = await _clean_old_mmds(agent_id, data_dir, retention_days)

    logger.info(
        "Reclaimed offload data for agent=%s: expired_entries=%d, orphan_refs=%d, old_mmds=%d",
        agent_id,
        expired_count,
        orphan_count,
        mmd_count,
    )

    return {
        "expired_entries_removed": expired_count,
        "orphan_refs_removed": orphan_count,
        "old_mmds_removed": mmd_count,
    }


async def clean_expired_entries(agent_id: str, data_dir: str, retention_days: int) -> int:
    """Remove offload.jsonl entries older than retention_days."""
    offload_dir = os.path.join(data_dir, agent_id, "offload")
    jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)

    def _clean():
        if not os.path.exists(jsonl_path):
            return 0
        cutoff_ms = int(time.time() * 1000) - retention_days * 86400 * 1000

        with open(jsonl_path, "r") as f:
            lines = f.readlines()

        kept = []
        removed = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "")
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    epoch_ms = int(dt.timestamp() * 1000)
                    if epoch_ms < cutoff_ms:
                        removed += 1
                        continue
                kept.append(line)
            except Exception:
                kept.append(line)

        with open(jsonl_path, "w") as f:
            for line in kept:
                f.write(line + "\n")

        return removed

    return await asyncio.to_thread(_clean)


async def clean_orphan_refs(agent_id: str, data_dir: str) -> int:
    """Remove ref/*.md files not referenced in any offload entry."""
    offload_dir = os.path.join(data_dir, agent_id, "offload")
    jsonl_path = os.path.join(offload_dir, _OFFLOAD_JSONL)
    refs_dir = os.path.join(offload_dir, _REFS_DIR)

    def _clean():
        if not os.path.exists(refs_dir):
            return 0

        referenced = set()
        if os.path.exists(jsonl_path):
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ref = entry.get("result_ref", "")
                        if ref:
                            referenced.add(os.path.basename(ref))
                    except Exception:
                        pass

        removed = 0
        for fname in os.listdir(refs_dir):
            if fname not in referenced:
                os.remove(os.path.join(refs_dir, fname))
                removed += 1

        return removed

    return await asyncio.to_thread(_clean)


async def _clean_old_mmds(agent_id: str, data_dir: str, retention_days: int) -> int:
    offload_dir = os.path.join(data_dir, agent_id, "offload")
    mmds_dir = os.path.join(offload_dir, _MMDS_DIR)

    def _clean():
        if not os.path.exists(mmds_dir):
            return 0

        cutoff = time.time() - retention_days * 86400
        removed = 0
        for fname in os.listdir(mmds_dir):
            fpath = os.path.join(mmds_dir, fname)
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                removed += 1

        return removed

    return await asyncio.to_thread(_clean)
