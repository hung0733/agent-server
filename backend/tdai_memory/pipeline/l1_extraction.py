from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

import openai

from backend.i18n import t
from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.models import MemoryRecord
from backend.tdai_memory.store.embedding import EmbeddingService
from backend.tdai_memory.store.postgres import PostgresStore
from backend.tdai_memory.store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """你是一个记忆提取助手。从对话中提取结构化记忆，分为三类：

1. **persona** (用户画像): 用户的基本信息、偏好、习惯、身份特征
2. **episodic** (事件记忆): 用户提到的具体事件、经历、活动（含活动时间）
3. **instruction** (指令记忆): 用户明确给出的指令、规则、偏好设置

要求：
- 每条记忆简洁准确，不超过100字
- 优先提取重要和可复用的信息
- 不要提取无意义或临时的闲聊内容
- 如果某类没有可提取的记忆，留空数组
- 对于 episodic 类型，如果提到活动时间，请在 metadata 字段中包含 activity_start_time 和 activity_end_time (ISO 8601)
- 每条记忆的 priority 值为 0-100：
  - 80-100: 非常重要的长期信息或核心指令
  - 50-79: 有价值的偏好或事件
  - 0-49: 一般信息
  - -1: 严格的全局指令（用户明确强调必须遵守的规则）

输出格式（严格JSON）：
```json
{
  "memories": [
    {
      "content": "记忆内容",
      "type": "persona|episodic|instruction",
      "priority": 80,
      "metadata": {}
    }
  ]
}
```

以下是已有的相关记忆（用于去重参考，避免创建重复记忆）：
{existing_memories_text}

请从以下对话中提取记忆：
{conversation_text}"""

_VALID_TYPES = {"persona", "episodic", "instruction"}


def _parse_llm_extraction_response(response_text: str) -> list[dict]:
    text = response_text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(t("tdai_memory.pipeline.l1_parse_json_failed"))
        return []

    if not isinstance(data, dict) or "memories" not in data:
        return []

    memories = data["memories"]
    if not isinstance(memories, list):
        return []

    result = []
    for m in memories:
        if not isinstance(m, dict):
            continue
        content = str(m.get("content", "")).strip()
        mem_type = str(m.get("type", "")).strip()
        if not content or mem_type not in _VALID_TYPES:
            continue
        try:
            priority = int(m.get("priority", 0))
        except (ValueError, TypeError):
            priority = 0
        priority = max(-1, min(100, priority))
        metadata = m.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        result.append({
            "content": content,
            "type": mem_type,
            "priority": priority,
            "metadata": metadata,
        })
    return result


async def run_l1_extraction(
    *,
    agent_id: str,
    session_key: str,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
    checkpoint_cursor: str | None = None,
) -> list[MemoryRecord]:
    after_timestamp_ms = 0
    if checkpoint_cursor:
        dt = datetime.fromisoformat(checkpoint_cursor)
        after_timestamp_ms = int(dt.timestamp() * 1000)

    l0_messages = await postgres.query_l0_for_l1(
        agent_id, session_key, after_timestamp_ms=after_timestamp_ms, limit=100
    )

    if not l0_messages:
        logger.debug(t("tdai_memory.pipeline.l1_no_l0_messages"), agent_id, session_key)
        return []

    conversation_lines = [f"[{m['role']}]: {m['message_text']}" for m in l0_messages]
    conversation_text = "\n".join(conversation_lines)

    existing_records = await postgres.query_l1_records(agent_id, limit=50)
    if existing_records:
        existing_memories_text = "\n".join(
            f"- [{r['type']}] {r['content']}" for r in existing_records
        )
    else:
        existing_memories_text = "(暂无已有记忆)"

    system_prompt = _EXTRACTION_PROMPT.format(
        existing_memories_text=existing_memories_text,
        conversation_text=conversation_text,
    )

    model = config.extraction.model or config.llm.model

    response = await llm_client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system_prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout_ms / 1000,
    )

    response_text = response.choices[0].message.content or ""
    extracted = _parse_llm_extraction_response(response_text)

    if not extracted:
        logger.debug(t("tdai_memory.pipeline.l1_no_memories_extracted"), agent_id)
        return []

    max_memories = config.extraction.max_memories_per_session
    now_iso = datetime.now(timezone.utc).isoformat()
    results: list[MemoryRecord] = []

    for item in extracted[:max_memories]:
        record = MemoryRecord(
            id=f"mem_{uuid4().hex[:12]}",
            agent_id=agent_id,
            content=item["content"],
            type=item["type"],
            priority=item["priority"],
            scene_name="",
            timestamps=[now_iso],
            created_at=now_iso,
            updated_at=now_iso,
            session_key=session_key,
            session_id="",
            metadata=item.get("metadata", {}),
        )

        if not config.extraction.enable_dedup:
            await postgres.upsert_l1(record)
            await qdrant.upsert_l1(record, None)
            results.append(record)
            continue

        try:
            query_vector = await embedding.embed(record.content)
        except Exception:
            logger.exception(t("tdai_memory.pipeline.l1_embed_failed"), record.id)
            await postgres.upsert_l1(record)
            await qdrant.upsert_l1(record, None)
            results.append(record)
            continue

        search_results = await qdrant.search_l1(agent_id, query_vector, limit=5)

        if not search_results or search_results[0]["score"] < 0.7:
            await postgres.upsert_l1(record)
            await qdrant.upsert_l1(record, query_vector)
            results.append(record)
            continue

        top = search_results[0]
        existing_id = top["id"]
        existing_content = top.get("content", "")
        existing_type = top.get("type", record.type)
        existing_priority = top.get("priority", record.priority)
        existing_timestamps = list(top.get("timestamps", []))
        existing_created_at = top.get("created_at", now_iso)
        existing_session_key = top.get("session_key", "")
        existing_session_id = top.get("session_id", "")

        if top["score"] > 0.85:
            updated = MemoryRecord(
                id=existing_id,
                agent_id=agent_id,
                content=existing_content,
                type=existing_type,
                priority=existing_priority,
                scene_name="",
                timestamps=existing_timestamps + [now_iso],
                created_at=existing_created_at,
                updated_at=now_iso,
                session_key=existing_session_key,
                session_id=existing_session_id,
            )
            await postgres.upsert_l1(updated)
            results.append(updated)
            logger.debug(
                t("tdai_memory.pipeline.l1_dedup_match"),
                record.id,
                existing_id,
                top["score"],
            )
        else:
            merged_content = f"{existing_content}\n{record.content}"
            merged = MemoryRecord(
                id=existing_id,
                agent_id=agent_id,
                content=merged_content,
                type=existing_type,
                priority=existing_priority,
                scene_name="",
                timestamps=existing_timestamps + [now_iso],
                created_at=existing_created_at,
                updated_at=now_iso,
                session_key=existing_session_key,
                session_id=existing_session_id,
            )
            await postgres.upsert_l1(merged)
            try:
                merged_vector = await embedding.embed(merged_content)
                await qdrant.upsert_l1(merged, merged_vector)
            except Exception:
                logger.exception(t("tdai_memory.pipeline.l1_reembed_failed"), existing_id)
            results.append(merged)
            logger.debug(
                t("tdai_memory.pipeline.l1_merge"),
                record.id,
                existing_id,
                top["score"],
            )

    logger.info(
        t("tdai_memory.pipeline.l1_done"),
        agent_id, session_key, len(extracted), len(results),
    )
    return results
