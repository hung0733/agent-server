from __future__ import annotations

import asyncio
import logging
import os

from qdrant_client import models

from ..store.embedding import EmbeddingService
from ..store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_PROFILE_FILES = {
    "persona": "persona.md",
    "soul": "SOUL.md",
    "identity": "IDENTITY.md",
}

_PROFILE_COLLECTION = "l3_profiles"


async def pull_profiles_to_local(agent_id: str, data_dir: str, qdrant: QdrantStore) -> list[dict]:
    agent_dir = os.path.join(data_dir, agent_id)
    os.makedirs(agent_dir, exist_ok=True)

    try:
        records, _ = await qdrant.client.scroll(
            collection_name=_PROFILE_COLLECTION,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value=agent_id),
                    )
                ]
            ),
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        logger.exception("Failed to pull profiles for agent %s", agent_id)
        return []

    profiles: list[dict] = []
    for record in records:
        payload = record.payload or {}
        profile_type = payload.get("profile_type", "")
        content = payload.get("content", "")
        filename = _PROFILE_FILES.get(profile_type)
        if filename and content:
            path = os.path.join(agent_dir, filename)

            def _write() -> None:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

            await asyncio.to_thread(_write)
            profiles.append({"type": profile_type, "id": record.id})

    return profiles


async def sync_local_profiles_to_store(
    agent_id: str,
    data_dir: str,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
) -> None:
    for profile_type, filename in _PROFILE_FILES.items():
        path = os.path.join(data_dir, agent_id, filename)

        def _read() -> str | None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                return None

        content = await asyncio.to_thread(_read)
        if content is None:
            continue

        try:
            vec = await embedding.embed(content)
        except Exception:
            logger.exception("Failed to embed profile %s for agent %s", profile_type, agent_id)
            continue

        profile_id = f"profile_{agent_id}_{profile_type}"
        await qdrant.client.upsert(
            collection_name=_PROFILE_COLLECTION,
            points=[
                models.PointStruct(
                    id=profile_id,
                    vector=vec,
                    payload={
                        "agent_id": agent_id,
                        "profile_type": profile_type,
                        "content": content,
                        "source_file": filename,
                    },
                )
            ],
        )
        logger.info("Synced profile %s for agent %s", profile_type, agent_id)
