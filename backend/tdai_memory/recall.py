from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from tdai_memory.config import MemoryConfig
from tdai_memory.models import RecalledMemory, RecallResult
from tdai_memory.store.embedding import EmbeddingService
from tdai_memory.store.postgres import PostgresStore
from tdai_memory.store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_GATEWAY_METADATA_RE = re.compile(
    r"<\|gateway_metadata\|>.*?</\|gateway_metadata\|>", re.DOTALL
)
_GATEWAY_CONTEXT_RE = re.compile(
    r"<\|gateway_context\|>.*?</\|gateway_context\|>", re.DOTALL
)
_IMAGE_BASE64_RE = re.compile(
    r"<\|image_base64\|>.*?</\|image_base64\|>", re.DOTALL
)

_SCENE_NAV_LINK_RE = re.compile(r"\[🔍.*?\]\(scene_nav:.*?\)")
_SCENE_NAV_SECTION_RE = re.compile(r"## 📑 场景导航.*?(?=\Z)", re.DOTALL)

_RRF_K = 60
_RRF_SCORE_THRESHOLD = 0.01

TOOLS_GUIDE = """<memory-tools-guide>
你可以使用以下記憶工具來檢索歷史記憶：

- **tdai_memory_search** — 搜尋結構化記憶（用戶畫像、事件記憶、指令記憶）。支持 keyword / embedding / hybrid 三種策略。
- **tdai_conversation_search** — 搜尋原始對話記錄（L0 層）。支持 keyword / embedding 策略。

使用建議：
1. 當用戶提到過去發生的事、偏好、或你感覺需要回顧歷史時，主動調用記憶工具。
2. 每次調用最多 3 次，如果 3 次都無相關結果，停止搜索，直接基於當前上下文回答。
3. 搜尋時使用簡潔的關鍵詞（2-8 個字），不要用完整句子。
4. 如果用戶明確要求搜尋特定記憶，優先使用 tdai_memory_search。
</memory-tools-guide>"""


def _sanitize_text(user_text: str) -> str:
    text = _GATEWAY_METADATA_RE.sub("", user_text)
    text = _GATEWAY_CONTEXT_RE.sub("", text)
    text = _IMAGE_BASE64_RE.sub("", text)
    return text.strip()


def _strip_scene_nav_markup(content: str) -> str:
    content = _SCENE_NAV_LINK_RE.sub("", content)
    content = _SCENE_NAV_SECTION_RE.sub("", content)
    return content.strip()


def _format_timestamp(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str


def _rrf_fusion(
    keyword_results: list[dict],
    vector_results: list[dict],
    k: int = _RRF_K,
) -> list[dict]:
    merged: dict[str, dict] = {}

    for rank_pos, item in enumerate(keyword_results):
        rrf = 1.0 / (k + rank_pos + 1)
        mid = item["id"]
        if mid not in merged:
            merged[mid] = {**item, "_rrf_score": rrf, "_source": "keyword"}
        else:
            merged[mid]["_rrf_score"] = merged[mid].get("_rrf_score", 0.0) + rrf
            if merged[mid].get("_source") != "vector":
                merged[mid].update(
                    {k: v for k, v in item.items() if k not in merged[mid]}
                )

    for rank_pos, item in enumerate(vector_results):
        rrf = 1.0 / (k + rank_pos + 1)
        mid = item["id"]
        if mid not in merged:
            merged[mid] = {**item, "_rrf_score": rrf, "_source": "vector"}
        else:
            merged[mid]["_rrf_score"] = merged[mid].get("_rrf_score", 0.0) + rrf
            merged[mid].update(
                {k: v for k, v in item.items() if k not in merged[mid]}
            )

    fused = sorted(merged.values(), key=lambda x: x["_rrf_score"], reverse=True)
    return fuseds


def _build_memory_line(item: dict) -> str:
    mem_type = item.get("type", "")
    scene_name = item.get("scene_name", "")
    content = item.get("content", "")

    tags = []
    if mem_type:
        tags.append(mem_type)
    if scene_name:
        tags.append(scene_name)
    tag_str = "|".join(tags)
    line = f"- [{tag_str}] {content}" if tag_str else f"- {content}"

    metadata = item.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    if isinstance(metadata, dict):
        start = metadata.get("activity_start_time")
        end = metadata.get("activity_end_time")
        if start and end and start == end:
            line += f" (活动时间: {_format_timestamp(start)})"
        elif start and end:
            line += f" (活动时间: {_format_timestamp(start)} ~ {_format_timestamp(end)})"
        elif start:
            line += f" (活动时间: {_format_timestamp(start)}起)"
        elif end:
            line += f" (活动时间: 至{_format_timestamp(end)})"

    return line


async def _read_file_async(filepath: str) -> str | None:
    def _read() -> str | None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    content = await asyncio.to_thread(_read)
    if content is not None:
        content = _strip_scene_nav_markup(content)
    return content


async def _do_hybrid_recall(
    agent_id: str,
    user_text: str,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    config: MemoryConfig,
) -> list[dict]:
    limit = config.recall.max_results
    threshold = config.recall.score_threshold

    try:
        keyword_task = postgres.search_l1_fts(agent_id, user_text, limit=limit * 2)
        embedding_task = embedding.embed(user_text)
        keyword_results, query_embedding = await asyncio.gather(
            keyword_task, embedding_task
        )
    except Exception:
        logger.warning(
            "Embedding failed during hybrid recall, falling back to keyword-only"
        )
        keyword_results = await postgres.search_l1_fts(
            agent_id, user_text, limit=limit
        )
        return [r for r in keyword_results if r.get("score", 0.0) >= threshold]

    vector_results = await qdrant.search_l1(
        agent_id, query_embedding, limit=limit * 2
    )

    vector_filtered = [r for r in vector_results if r.get("score", 0.0) >= threshold]

    fused = _rrf_fusion(keyword_results, vector_filtered)
    filtered = [r for r in fused if r.get("_rrf_score", 0.0) >= _RRF_SCORE_THRESHOLD]
    return filtered[:limit]


async def _do_embedding_recall(
    agent_id: str,
    user_text: str,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    config: MemoryConfig,
) -> list[dict]:
    limit = config.recall.max_results
    threshold = config.recall.score_threshold
    query_embedding = await embedding.embed(user_text)
    results = await qdrant.search_l1(agent_id, query_embedding, limit=limit * 2)
    return [r for r in results if r.get("score", 0.0) >= threshold][:limit]


async def _do_keyword_recall(
    agent_id: str,
    user_text: str,
    postgres: PostgresStore,
    config: MemoryConfig,
) -> list[dict]:
    limit = config.recall.max_results
    threshold = config.recall.score_threshold
    results = await postgres.search_l1_fts(agent_id, user_text, limit=limit * 2)
    return [r for r in results if r.get("score", 0.0) >= threshold][:limit]


def _results_to_recalled(results: list[dict]) -> list[RecalledMemory]:
    recalled: list[RecalledMemory] = []
    for item in results:
        score = item.get("_rrf_score") or item.get("score", 0.0)
        recalled.append(
            RecalledMemory(
                id=item.get("id", ""),
                content=item.get("content", ""),
                type=item.get("type", ""),
                score=float(score),
                scene_name=item.get("scene_name", ""),
                priority=item.get("priority", 0),
                timestamps=item.get("timestamps", []),
            )
        )
    return recalled


async def perform_auto_recall(
    *,
    agent_id: str,
    user_text: str,
    session_key: str,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    data_dir: str,
    config: MemoryConfig,
) -> RecallResult:
    t_start = time.monotonic()

    sanitized = _sanitize_text(user_text)
    do_search = len(sanitized) >= 2
    logger.debug("Recall sanitized %d→%d chars", len(user_text), len(sanitized))

    agent_dir = os.path.join(data_dir, agent_id)

    persona_content, soul_content, identity_content = await asyncio.gather(
        _read_file_async(os.path.join(agent_dir, "persona.md")),
        _read_file_async(os.path.join(agent_dir, "SOUL.md")),
        _read_file_async(os.path.join(agent_dir, "IDENTITY.md")),
    )
    scene_nav_text = await _load_scene_nav(agent_dir)

    recalled_memories: list[RecalledMemory] = []
    strategy = "hybrid"
    prepend_context: str | None = None

    if do_search:
        recall_coro = _perform_recall(
            agent_id=agent_id,
            sanitized_text=sanitized,
            postgres=postgres,
            qdrant=qdrant,
            embedding=embedding,
            config=config,
        )

        try:
            results, strategy = await asyncio.wait_for(
                recall_coro,
                timeout=config.recall.timeout_ms / 1000.0,
            )
            recalled_memories = _results_to_recalled(results)
            prepend_context = _build_prepend_context(recalled_memories)
        except asyncio.TimeoutError:
            logger.warning(
                "Auto-recall timed out after %dms for agent=%s",
                config.recall.timeout_ms,
                agent_id,
            )

    append_system_context = _build_append_context(
        persona_content, soul_content, identity_content, scene_nav_text
    )

    if not prepend_context and not append_system_context:
        logger.debug("Recall empty result for agent=%s (%.0fms)", agent_id, (time.monotonic() - t_start) * 1000)
        return RecallResult()

    logger.debug(
        "Recall done: agent=%s strategy=%s memories=%d persona=%s soul=%s identity=%s scene=%s (%.0fms)",
        agent_id, strategy, len(recalled_memories),
        "yes" if persona_content else "no",
        "yes" if soul_content else "no",
        "yes" if identity_content else "no",
        "yes" if scene_nav_text else "no",
        (time.monotonic() - t_start) * 1000,
    )
    return RecallResult(
        prepend_context=prepend_context,
        append_system_context=append_system_context,
        recalled_l1_memories=recalled_memories,
        recalled_l3_persona=persona_content,
        recalled_l3_soul=soul_content,
        recalled_l3_identity=identity_content,
        recall_strategy=strategy,
    )


async def _perform_recall(
    *,
    agent_id: str,
    sanitized_text: str,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    config: MemoryConfig,
) -> tuple[list[dict], str]:
    strategy = config.recall.strategy

    if strategy == "keyword":
        results = await _do_keyword_recall(agent_id, sanitized_text, postgres, config)
        return results, "keyword"

    if strategy == "embedding":
        try:
            results = await _do_embedding_recall(
                agent_id, sanitized_text, qdrant, embedding, config
            )
            return results, "embedding"
        except Exception:
            logger.warning(
                "Embedding recall failed, falling back to keyword for agent=%s",
                agent_id,
            )
            results = await _do_keyword_recall(agent_id, sanitized_text, postgres, config)
            return results, "keyword"

    try:
        results = await _do_hybrid_recall(
            agent_id, sanitized_text, postgres, qdrant, embedding, config
        )
        return results, "hybrid"
    except Exception:
        logger.warning(
            "Hybrid recall failed, falling back to keyword for agent=%s",
            agent_id,
        )
        results = await _do_keyword_recall(agent_id, sanitized_text, postgres, config)
        return results, "keyword"


async def _load_scene_nav(agent_dir: str) -> str | None:
    def _read() -> dict | None:
        path = os.path.join(agent_dir, "scene_index.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    scene_index = await asyncio.to_thread(_read)
    if not scene_index:
        return None

    scenes = scene_index.get("scenes") or scene_index
    if not isinstance(scenes, list) or not scenes:
        return None

    lines = ["## 📑 场景导航"]
    for scene in scenes:
        name = scene.get("name", "")
        if not name:
            continue
        label = scene.get("label", name)
        summary = scene.get("summary", "")
        memory_count = scene.get("memory_count", 0)
        if summary:
            lines.append(f"- [🔍 {label}](scene_nav:{name}) — {summary} [{memory_count} memories]")
        else:
            lines.append(f"- [🔍 {label}](scene_nav:{name}) [{memory_count} memories]")

    if len(lines) == 1:
        return None

    return "\n".join(lines)


def _build_prepend_context(memories: list[RecalledMemory]) -> str | None:
    if not memories:
        return None

    lines = ["<relevant-memories>"]
    for mem in memories:
        mem_dict = mem.model_dump()
        line = _build_memory_line(mem_dict)
        lines.append(line)
    lines.append("</relevant-memories>")

    return "\n".join(lines)


def _build_append_context(
    persona: str | None,
    soul: str | None,
    identity: str | None,
    scene_nav: str | None,
) -> str | None:
    parts: list[str] = []

    if persona:
        parts.append("<user-persona>\n" + persona + "\n</user-persona>")

    if soul:
        parts.append("<agent-soul>\n" + soul + "\n</agent-soul>")

    if identity:
        parts.append("<agent-identity>\n" + identity + "\n</agent-identity>")

    if scene_nav:
        parts.append("<scene-navigation>\n" + scene_nav + "\n</scene-navigation>")

    parts.append(TOOLS_GUIDE)

    if not any(p != TOOLS_GUIDE for p in parts):
        return None

    return "\n\n".join(parts)
