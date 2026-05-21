from __future__ import annotations

import logging

from backend.tdai_memory.models import ConversationSearchParams, MemorySearchParams, SearchResult
from backend.tdai_memory.store.embedding import EmbeddingService
from backend.tdai_memory.store.postgres import PostgresStore
from backend.tdai_memory.store.qdrant import QdrantStore

from .recall import _rrf_fusion

logger = logging.getLogger(__name__)


async def search_memories(
    params: MemorySearchParams,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
) -> SearchResult:
    strategy = params.strategy

    if strategy == "keyword":
        items = await postgres.search_l1_fts(params.agent_id, params.query, params.top_k)
    elif strategy == "embedding":
        query_vec = await embedding.embed(params.query)
        items = await qdrant.search_l1(params.agent_id, query_vec, params.top_k)
    else:
        keyword_items = await postgres.search_l1_fts(params.agent_id, params.query, params.top_k)
        query_vec = await embedding.embed(params.query)
        vector_items = await qdrant.search_l1(params.agent_id, query_vec, params.top_k)
        items = _rrf_fusion(keyword_items, vector_items)

    if params.score_threshold > 0:
        items = [i for i in items if i.get("score", 0) >= params.score_threshold]

    if params.type_filter:
        items = [i for i in items if i.get("type") == params.type_filter]
    if params.scene_filter:
        items = [i for i in items if i.get("scene_name") == params.scene_filter]

    lines = []
    for item in items:
        mem_type = item.get("type", "")
        scene = item.get("scene_name", "")
        content = item.get("content", "")
        priority = item.get("priority", 0)
        lines.append(f"- [{mem_type}|{scene}] {content} [priority={priority}]")

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
    query_vec = await embedding.embed(params.query)
    items = await qdrant.search_l0(params.agent_id, query_vec, params.top_k)

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
        strategy="vector",
        items=items,
    )
