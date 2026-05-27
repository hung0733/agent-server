from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

import openai

from backend.i18n import t
from ..config import MemoryConfig
from ..llm_options import tdai_memory_thinking_kwargs
from ..models import MemoryRecord
from ..store.embedding import EmbeddingService
from ..store.postgres import PostgresStore
from ..store.qdrant import QdrantStore

from ..utils.sanitize import sanitize_json_for_parse, should_extract_l1

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
- 每条记忆需包含 source_message_ids: 引用该记忆来源的对话消息序号列表（从 1 开始）
- 对于 episodic 类型，如果提到活动时间，请在 metadata 字段中包含 activity_start_time 和 activity_end_time (ISO 8601)
- 每条记忆的 priority 值为 0-100：
  - 80-100: 非常重要的长期信息或核心指令
  - 50-79: 有价值的偏好或事件
  - 0-49: 一般信息
  - -1: 严格的全局指令（用户明确强调必须遵守的规则）

输出格式（严格JSON）：
```json
{{
  "scenes": [
    {{
      "scene_name": "场景标籤（例如：技术偏好、工作习惯）",
      "message_ids": [1, 2],
      "memories": [
        {{
          "content": "记忆内容",
          "type": "persona|episodic|instruction",
          "priority": 80,
          "source_message_ids": [1],
          "metadata": {{}}
        }}
      ]
    }}
  ]
}}
```

以下是已有的相关记忆（用于去重参考，避免创建重复记忆）：
{existing_memories_text}

请从以下对话中提取记忆：
{conversation_text}"""

_VALID_TYPES = {"persona", "episodic", "instruction"}


def _first_conversation_metadata(l0_messages: list[dict]) -> dict:
    for message in l0_messages:
        metadata = message.get("metadata")
        if isinstance(metadata, dict) and metadata:
            return metadata
    return {}


def _session_conversation_metadata(l0_messages: list[dict]) -> dict:
    metadata = _first_conversation_metadata(l0_messages)
    if not metadata:
        return {}

    result: dict = {}
    conversation_kind = metadata.get("conversation_kind")
    if isinstance(conversation_kind, str) and conversation_kind:
        result["conversation_kind"] = conversation_kind

    sender = {
        "name": str(metadata.get("sender_name") or ""),
        "type": str(metadata.get("sender_type") or "unknown"),
    }
    receiver = {
        "name": str(metadata.get("recv_name") or ""),
        "type": str(metadata.get("recv_type") or "agent"),
    }
    result["participants"] = {
        "sender": sender,
        "receiver": receiver,
    }
    return result


def _format_message_line(message: dict) -> str:
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    sender_type = str(metadata.get("sender_type") or "unknown")
    sender_name = str(metadata.get("sender_name") or "").strip()
    recv_type = str(metadata.get("recv_type") or "agent")
    recv_name = str(metadata.get("recv_name") or "").strip()

    if sender_name or recv_name:
        left = f"{sender_type}: {sender_name}" if sender_name else sender_type
        right = f"{recv_type}: {recv_name}" if recv_name else recv_type
        prefix = f"[{left} -> {right}][{message['role']}]"
    else:
        prefix = f"[{message['role']}]"
    return f"{prefix}: {message['message_text']}"


def _parse_llm_extraction_response(response_text: str) -> list[dict]:
    text = response_text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(t("tdai_memory.pipeline.failed_parse_llm_json"))
        return []

    if not isinstance(data, dict):
        return []

    if "scenes" in data:
        result = []
        scenes = data["scenes"]
        if not isinstance(scenes, list):
            return []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_name = str(scene.get("scene_name", "")).strip()
            memories = scene.get("memories", [])
            if not isinstance(memories, list):
                continue
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
                    "scene_name": scene_name,
                })
        return result

    if "memories" not in data:
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
    after_recorded_at_epoch_ms = 0
    if checkpoint_cursor:
        dt = datetime.fromisoformat(checkpoint_cursor)
        after_recorded_at_epoch_ms = int(dt.timestamp() * 1000)

    l0_messages = await postgres.query_l0_for_l1(
        agent_id, session_key, after_recorded_at_epoch_ms=after_recorded_at_epoch_ms, limit=100
    )

    if not l0_messages:
        logger.debug(t("tdai_memory.pipeline.no_l0_messages"), agent_id, session_key)
        return []

    filtered_l0 = []
    for m in l0_messages:
        content = (m.get("message_text") or "").strip()
        if len(content) < 2:
            continue
        if len(content) > 50000:
            continue
        if content.startswith("```") and content.endswith("```") and len(content) < 50:
            continue
        filtered_l0.append(m)
    l0_messages = filtered_l0

    if not l0_messages:
        logger.debug(t("tdai_memory.pipeline.no_l0_messages"), agent_id, session_key)
        return []

    l0_msgs_for_check = [
        {"role": m["role"], "content": m["message_text"]} for m in l0_messages
    ]
    if not should_extract_l1(l0_msgs_for_check):
        logger.debug(t("tdai_memory.pipeline.l0_quality_gate_failed"), agent_id)
        return []

    split_idx = int(len(l0_messages) * 0.7)
    background = l0_messages[:split_idx][-50:]
    new = l0_messages[split_idx:][-30:]

    def _build_section(messages, label):
        lines = [_format_message_line(m) for m in messages]
        return f"## {label}\n" + "\n".join(lines)

    conversation_text = (
        _build_section(background, "背景对话")
        + "\n\n"
        + _build_section(new, "新对话")
    )

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
        **tdai_memory_thinking_kwargs(model),
    )

    response_text = response.choices[0].message.content or ""
    response_text = sanitize_json_for_parse(response_text)
    extracted = _parse_llm_extraction_response(response_text)

    if not extracted:
        logger.debug(t("tdai_memory.pipeline.no_memories_extracted"), agent_id)
        return []

    max_memories = config.extraction.max_memories_per_session
    now_iso = datetime.now(timezone.utc).isoformat()
    conversation_metadata = _session_conversation_metadata(l0_messages)

    new_memories: list[MemoryRecord] = []
    for item in extracted[:max_memories]:
        item_metadata = item.get("metadata", {})
        if not isinstance(item_metadata, dict):
            item_metadata = {}
        metadata = {**item_metadata}
        for key, value in conversation_metadata.items():
            metadata.setdefault(key, value)
        record = MemoryRecord(
            id=f"mem_{uuid4().hex[:12]}",
            agent_id=agent_id,
            content=item["content"],
            type=item["type"],
            priority=item["priority"],
            scene_name=item.get("scene_name", ""),
            source_message_ids=item.get("source_message_ids", []),
            timestamps=[now_iso],
            created_at=now_iso,
            updated_at=now_iso,
            session_key=session_key,
            session_id="",
            metadata=metadata,
        )
        new_memories.append(record)

    from .l1_dedup import batch_dedup

    final_memories = await batch_dedup(
        agent_id=agent_id,
        new_memories=new_memories,
        postgres=postgres,
        qdrant=qdrant,
        embedding=embedding,
        llm_client=llm_client,
        config=config,
    )

    results: list[MemoryRecord] = []
    for mem in final_memories:
        try:
            await postgres.upsert_l1(mem)
            if embedding.is_ready():
                emb = await embedding.embed(mem.content)
                await qdrant.upsert_l1(mem, emb)
            else:
                await qdrant.upsert_l1(mem, None)
            results.append(mem)
        except Exception:
            logger.exception(t("tdai_memory.pipeline.upsert_memory_failed"), mem.id)

    logger.info(
        t("tdai_memory.pipeline.l1_extraction_done"),
        agent_id, session_key, len(extracted), len(results),
    )
    return results
