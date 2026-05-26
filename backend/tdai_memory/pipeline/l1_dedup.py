from __future__ import annotations

import json
import logging
from uuid import uuid4

import openai
from openai import AsyncOpenAI

from backend.i18n import t
from ..config import MemoryConfig
from ..models import MemoryRecord
from ..store.embedding import EmbeddingService
from ..store.postgres import PostgresStore
from ..store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

DEDUP_SYSTEM_PROMPT = """# Memory Conflict Detector

你是記憶衝突檢測器。比較新記憶與候選記憶池，判斷是否有衝突/重複。

## 動作類型
- **store**: 新記憶不存在衝突，直接儲存
- **update**: 新記憶是舊記憶的更新版，更新舊記憶內容
- **merge**: 新記憶與舊記憶部分關聯，合併內容。如果 type/priority 需要變更，在 merged_type/merged_priority 指定
- **skip**: 新記憶完全被舊記憶包含，無需儲存

## 規則
- 合併時保留重要細節，避免資訊遺失
- 可在 persona/episodic/instruction 之間合併
- 如果新記憶與多個候選關聯，target_ids 設為所有相關候選
- priority 值 0-100，-1 表示全域指令

輸出格式（純 JSON，不含 markdown code block）:
{"decisions": [{"action": "store|update|merge|skip", "target_ids": ["mem_abc"], "merged_content": "合併內容（僅 merge 需要）", "merged_type": "instruction（僅 merge 且需變更 type 時）", "merged_priority": 80（僅 merge 且需變更 priority 時）}]}"""


async def batch_dedup(
    *,
    agent_id: str,
    new_memories: list[MemoryRecord],
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    llm_client: AsyncOpenAI,
    config: MemoryConfig,
) -> list[MemoryRecord]:
    if not config.extraction.enable_dedup or not new_memories:
        return new_memories

    top_k = getattr(config.embedding, "conflict_recall_top_k", 5) or 5
    model = config.extraction.model or config.llm.model

    conflict_batch: list[dict] = []
    new_mem_ids = {m.id for m in new_memories}

    texts = [m.content for m in new_memories]
    embs = await embedding.embed_batch(texts)
    emb_map = {m.id: emb for m, emb in zip(new_memories, embs)}

    for new_mem in new_memories:
        emb = emb_map.get(new_mem.id)
        if emb is None:
            continue

        try:
            candidates = await qdrant.search_l1(agent_id, emb, limit=top_k)
        except Exception:
            logger.warning(
                t("tdai_memory.pipeline.dedup_search_failed_storing_new"),
                new_mem.id,
                exc_info=True,
            )
            continue

        if len(candidates) < 3:
            try:
                fts_results = await postgres.search_l1_fts(agent_id, new_mem.content, limit=top_k)
                merged: dict[str, dict] = {}
                for c in candidates:
                    merged[c.get("id", "")] = c
                for f in fts_results:
                    fid = f.get("id", "")
                    if fid not in merged or (f.get("score", 0) > merged[fid].get("score", 0)):
                        merged[fid] = f
                candidates = list(merged.values())
            except Exception:
                logger.exception(t("tdai_memory.pipeline.fts_recall_failed"), new_mem.id)

        high_conflicts = [c for c in candidates if c.get("score", 0) >= 0.7]
        if not high_conflicts:
            continue

        existing = []
        for c in high_conflicts:
            cid = c.get("id", "")
            if cid in new_mem_ids:
                continue
            existing.append(
                {
                    "id": cid,
                    "content": c.get("content", ""),
                    "type": c.get("type", ""),
                    "priority": c.get("priority", 0),
                    "score": c.get("score", 0),
                }
            )

        if existing:
            conflict_batch.append(
                {
                    "new_id": new_mem.id,
                    "new_content": new_mem.content,
                    "new_type": new_mem.type,
                    "new_priority": new_mem.priority,
                    "candidates": existing,
                }
            )

    if not conflict_batch:
        return new_memories

    user_prompt = json.dumps({"conflicts": conflict_batch}, ensure_ascii=False, indent=2)

    try:
        response = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": DEDUP_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=config.llm.max_tokens,
            timeout=config.llm.timeout_ms / 1000.0,
        )
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)
    except Exception:
        logger.exception(t("tdai_memory.pipeline.llm_batch_dedup_failed_simple"))
        return _simple_dedup(new_memories, conflict_batch, postgres, embedding, qdrant, agent_id)

    decisions = data.get("decisions", [])
    decisions_by_new_id: dict[str, dict] = {d.get("new_id", ""): d for d in decisions}

    result: list[MemoryRecord] = []
    for new_mem in new_memories:
        decision = decisions_by_new_id.get(new_mem.id)
        if not decision:
            result.append(new_mem)
            continue

        action = decision.get("action", "store")

        if action == "store":
            result.append(new_mem)

        elif action == "skip":
            continue

        elif action in ("update", "merge"):
            target_ids = decision.get("target_ids", [])
            if isinstance(target_ids, str):
                target_ids = [target_ids]

            merged_content = decision.get("merged_content") or f"{new_mem.content}\n\n{new_mem.content}"
            merged_type = decision.get("merged_type") or new_mem.type
            merged_priority = decision.get("merged_priority")
            if merged_priority is None:
                merged_priority = new_mem.priority

            for tid in target_ids:
                try:
                    await _update_existing(
                        tid, merged_content, merged_type, merged_priority,
                        postgres, embedding, qdrant, agent_id, new_mem
                    )
                except Exception:
                    logger.exception(t("tdai_memory.pipeline.update_existing_mem_failed"), tid)

            if action == "merge":
                new_mem.content = merged_content
                new_mem.type = merged_type
                new_mem.priority = merged_priority
                result.append(new_mem)

    return result


async def _update_existing(
    record_id: str,
    content: str,
    mem_type: str,
    priority: int,
    postgres: PostgresStore,
    embedding: EmbeddingService,
    qdrant: QdrantStore,
    agent_id: str,
    new_mem: MemoryRecord,
) -> None:
    from datetime import datetime, timezone

    rows = await postgres.query_l1_records(agent_id, limit=1000)
    existing = None
    for r in rows:
        if r.get("id") == record_id:
            existing = r
            break

    if existing is None:
        return

    record = MemoryRecord(
        id=record_id,
        agent_id=agent_id,
        content=content,
        type=mem_type,
        priority=priority,
        scene_name=existing.get("scene_name", ""),
        timestamps=(
            list(existing.get("timestamps", []))
            + list(new_mem.timestamps)
            + [datetime.now(timezone.utc).isoformat()]
        ),
        created_at=str(existing.get("created_at", "")),
        updated_at=datetime.now(timezone.utc).isoformat(),
        session_key=str(existing.get("session_key", "")),
        session_id=str(existing.get("session_id", "")),
    )

    await postgres.upsert_l1(record)

    try:
        emb = await embedding.embed(content)
        await qdrant.upsert_l1(record, emb)
    except Exception:
        logger.exception(t("tdai_memory.pipeline.update_dedup_embedding_failed"), record_id)


def _simple_dedup(
    new_memories: list[MemoryRecord],
    conflict_batch: list[dict],
    postgres: PostgresStore,
    embedding: EmbeddingService,
    qdrant: QdrantStore,
    agent_id: str,
) -> list[MemoryRecord]:
    skip_ids: set[str] = set()
    for item in conflict_batch:
        best = max(item["candidates"], key=lambda c: c.get("score", 0), default=None)
        if best is None:
            continue
        score = best.get("score", 0)
        if score >= 0.85:
            skip_ids.add(item["new_id"])
        elif score >= 0.7:
            cid = best["id"]
            # append content as simple merge
            new_mem = next((m for m in new_memories if m.id == item["new_id"]), None)
            if new_mem:
                import asyncio
                asyncio.create_task(
                    _update_existing(
                        cid,
                        f"{best.get('content', '')}\n\n{new_mem.content}",
                        best.get("type", new_mem.type),
                        max(best.get("priority", 0), new_mem.priority),
                        postgres,
                        embedding,
                        qdrant,
                        agent_id,
                        new_mem,
                    )
                )

    return [m for m in new_memories if m.id not in skip_ids]
