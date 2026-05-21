from __future__ import annotations

import logging

from qdrant_client import AsyncQdrantClient, models

from backend.tdai_memory.models import L0Record, MemoryRecord

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(self, qdrant_url: str, vector_dimensions: int) -> None:
        self.client = AsyncQdrantClient(url=qdrant_url)
        self.dimensions = vector_dimensions

    async def initialize(self) -> None:
        collections = await self.client.get_collections()
        existing = {c.name for c in collections.collections}

        if "l0_conversations" not in existing:
            await self.client.create_collection(
                collection_name="l0_conversations",
                vectors_config=models.VectorParams(
                    size=self.dimensions,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
            )
            await self.client.create_payload_index(
                collection_name="l0_conversations",
                field_name="agent_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

        if "l1_memories" not in existing:
            await self.client.create_collection(
                collection_name="l1_memories",
                vectors_config=models.VectorParams(
                    size=self.dimensions,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
            )
            await self.client.create_payload_index(
                collection_name="l1_memories",
                field_name="agent_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

        logger.info("QdrantStore initialized")

    async def close(self) -> None:
        await self.client.close()

    async def upsert_l0(
        self, record: L0Record, embedding: list[float] | None = None
    ) -> None:
        if not embedding:
            return
        await self.client.upsert(
            collection_name="l0_conversations",
            points=[
                models.PointStruct(
                    id=record.id,
                    vector=embedding,
                    payload=record.model_dump(),
                )
            ],
        )

    async def delete_l0(self, record_id: str) -> None:
        await self.client.delete(
            collection_name="l0_conversations",
            points_selector=models.PointIdsList(
                points=[record_id],
            ),
        )

    async def search_l0(
        self, agent_id: str, query_embedding: list[float], limit: int = 10
    ) -> list[dict]:
        results = await self.client.search(
            collection_name="l0_conversations",
            query_vector=query_embedding,
            limit=limit,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value=agent_id),
                    )
                ]
            ),
            with_payload=True,
        )
        return [
            {"id": r.id, "score": r.score, **r.payload}
            for r in results
        ]

    async def upsert_l1(
        self, record: MemoryRecord, embedding: list[float] | None = None
    ) -> None:
        if not embedding:
            return
        await self.client.upsert(
            collection_name="l1_memories",
            points=[
                models.PointStruct(
                    id=record.id,
                    vector=embedding,
                    payload=record.model_dump(),
                )
            ],
        )

    async def delete_l1(self, record_id: str) -> None:
        await self.client.delete(
            collection_name="l1_memories",
            points_selector=models.PointIdsList(
                points=[record_id],
            ),
        )

    async def search_l1(
        self, agent_id: str, query_embedding: list[float], limit: int = 10
    ) -> list[dict]:
        results = await self.client.search(
            collection_name="l1_memories",
            query_vector=query_embedding,
            limit=limit,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value=agent_id),
                    )
                ]
            ),
            with_payload=True,
        )
        return [
            {"id": r.id, "score": r.score, **r.payload}
            for r in results
        ]

    async def count_l0(self, agent_id: str) -> int:
        result = await self.client.count(
            collection_name="l0_conversations",
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value=agent_id),
                    )
                ]
            ),
        )
        return result.count

    async def count_l1(self, agent_id: str) -> int:
        result = await self.client.count(
            collection_name="l1_memories",
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value=agent_id),
                    )
                ]
            ),
        )
        return result.count
