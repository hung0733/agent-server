from __future__ import annotations

import logging

from .models import ConversationSearchParams, MemorySearchParams, SearchResult
from .store.embedding import EmbeddingService
from .store.postgres import PostgresStore
from .store.qdrant import QdrantStore

from .recall import _rrf_fusion

logger = logging.getLogger(__name__)


async def search_memories(
    params: MemorySearchParams,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
) -> SearchResult:
    query = params.query.strip()
    if not query:
        return SearchResult(text="", total=0, strategy=params.strategy)

    strategy = params.strategy

    if strategy == "keyword":
        items = await postgres.search_l1_fts(params.agent_id, params.query, params.top_k)
    elif strategy == "embedding":
        try:
            query_vec = await embedding.embed(params.query)
            items = await qdrant.search_l1(params.agent_id, query_vec, params.top_k)
        except Exception:
            items = await postgres.search_l1_fts(params.agent_id, params.query, params.top_k)
            strategy = "keyword"
    else:
        fts_available = postgres.is_fts_available()
        try:
            keyword_items = (
                await postgres.search_l1_fts(params.agent_id, params.query, params.top_k * 3)
                if fts_available
                else []
            )
            query_vec = await embedding.embed(params.query)
            vector_items = await qdrant.search_l1(params.agent_id, query_vec, params.top_k * 3)
        except Exception:
            keyword_items = await postgres.search_l1_fts(params.agent_id, params.query, params.top_k)
            vector_items = []

        if keyword_items and vector_items:
            items = _rrf_fusion(keyword_items, vector_items)
        elif vector_items:
            items = vector_items
            strategy = "embedding"
        elif keyword_items:
            items = keyword_items
            strategy = "keyword"
        else:
            items = []

    if params.score_threshold > 0:
        items = [i for i in items if i.get("score", 0) >= params.score_threshold]

    items = items[: params.top_k]

    if params.type_filter:
        items = [i for i in items if i.get("type") == params.type_filter]
    if params.scene_filter:
        sf = params.scene_filter.lower()
        items = [i for i in items if sf in (i.get("scene_name") or "").lower()]

    lines = []
    for item in items:
        mem_type = item.get("type", "")
        scene = item.get("scene_name", "")
        content = item.get("content", "")
        priority = item.get("priority", 0)
        tags = [mem_type] if mem_type else []
        if scene:
            tags.append(scene)
        tag_str = "|".join(tags)
        line = f"- [{tag_str}] {content}"
        if priority == -1:
            line += " (global instruction)"
        else:
            line += f" [priority={priority}]"
        lines.append(line)

    return SearchResult(
        text="\n".join(lines),
        total=len(items),
        strategy=strategy,
        items=items,
    )


async def search_conversations(
    params: ConversationSearchParams,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
) -> SearchResult:
    query = params.query.strip()
    if not query:
        return SearchResult(text="", total=0, strategy="fts")

    fts_items = await postgres.search_l0_fts(
        params.agent_id, params.query, params.top_k * 3
    )

    try:
        query_vec = await embedding.embed(params.query)
        vector_items = await qdrant.search_l0(
            params.agent_id, query_vec, params.top_k * 3
        )
    except Exception:
        vector_items = []

    if vector_items:
        items = _rrf_fusion(fts_items, vector_items)
        strategy = "hybrid"
    else:
        items = fts_items
        strategy = "fts"

    items = items[: params.top_k]

    if params.session_key:
        items = [i for i in items if i.get("session_key") == params.session_key]

    lines = []
    for item in items:
        role = item.get("role", "")
        message_text = item.get("message_text", "")
        recorded_at = item.get("recorded_at", "")
        lines.append(f"[{role}] {message_text} (at {recorded_at})")

    return SearchResult(
        text="\n".join(lines),
        total=len(items),
        strategy=strategy,
        items=items,
    )
