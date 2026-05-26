from __future__ import annotations

import logging
import uuid

from qdrant_client import AsyncQdrantClient, models

from backend.i18n import t
from ..models import L0Record, MemoryRecord

logger = logging.getLogger(__name__)

_POINT_ID_NAMESPACE = uuid.UUID("8bd66d4a-9056-4a0d-bd69-e97f1562a9d4")


def _to_point_id(record_id: str) -> str:
    try:
        return str(uuid.UUID(record_id))
    except ValueError:
        return str(uuid.uuid5(_POINT_ID_NAMESPACE, record_id))


class QdrantStore:
    def __init__(
        self,
        qdrant_url: str,
        vector_dimensions: int,
        l0_collection: str = "l0_conversations",
        l1_collection: str = "l1_memories",
    ) -> None:
        self.client = AsyncQdrantClient(url=qdrant_url)
        self.dimensions = vector_dimensions
        self.l0_collection = l0_collection
        self.l1_collection = l1_collection

    async def initialize(self) -> None:
        collections = await self.client.get_collections()
        existing = {c.name for c in collections.collections}

        if self.l0_collection not in existing:
            await self.client.create_collection(
                collection_name=self.l0_collection,
                vectors_config=models.VectorParams(
                    size=self.dimensions,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
            )
            await self.client.create_payload_index(
                collection_name=self.l0_collection,
                field_name="agent_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

        if self.l1_collection not in existing:
            await self.client.create_collection(
                collection_name=self.l1_collection,
                vectors_config=models.VectorParams(
                    size=self.dimensions,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
            )
            await self.client.create_payload_index(
                collection_name=self.l1_collection,
                field_name="agent_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

        logger.info(t("tdai_memory.store.qdrant_initialized"))

    async def close(self) -> None:
        await self.client.close()

    async def upsert_l0(
        self, record: L0Record, embedding: list[float] | None = None
    ) -> None:
        if not embedding:
            return
        await self.client.upsert(
            collection_name=self.l0_collection,
            points=[
                models.PointStruct(
                    id=_to_point_id(record.id),
                    vector=embedding,
                    payload=record.model_dump(),
                )
            ],
        )

    async def delete_l0(self, record_id: str) -> None:
        await self.client.delete(
            collection_name=self.l0_collection,
            points_selector=models.PointIdsList(
                points=[_to_point_id(record_id)],
            ),
        )

    async def search_l0(
        self, agent_id: str, query_embedding: list[float], limit: int = 10
    ) -> list[dict]:
        response = await self.client.query_points(
            collection_name=self.l0_collection,
            query=query_embedding,
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
        results = response.points
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
            collection_name=self.l1_collection,
            points=[
                models.PointStruct(
                    id=_to_point_id(record.id),
                    vector=embedding,
                    payload=record.model_dump(),
                )
            ],
        )

    async def delete_l1(self, record_id: str) -> None:
        await self.client.delete(
            collection_name=self.l1_collection,
            points_selector=models.PointIdsList(
                points=[_to_point_id(record_id)],
            ),
        )

    async def search_l1(
        self, agent_id: str, query_embedding: list[float], limit: int = 10
    ) -> list[dict]:
        response = await self.client.query_points(
            collection_name=self.l1_collection,
            query=query_embedding,
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
        results = response.points
        return [
            {"id": r.id, "score": r.score, **r.payload}
            for r in results
        ]

    async def count_l0(self, agent_id: str) -> int:
        result = await self.client.count(
            collection_name=self.l0_collection,
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
            collection_name=self.l1_collection,
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
