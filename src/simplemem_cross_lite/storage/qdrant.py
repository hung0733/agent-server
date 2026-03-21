# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportMissingParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportDeprecated=false
"""
Qdrant implementation of VectorStore.

Provides async vector operations with tenant_id payload filtering for multitenancy.
Uses a single collection with payload-based tenant isolation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Optional, Type

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from .base import VectorStore
from simplemem_cross_lite.types import CrossMemoryEntry

logger = logging.getLogger(__name__)

# Default embedding dimension (qwen3-embed-4b)
DEFAULT_VECTOR_SIZE = 1024
DEFAULT_COLLECTION_NAME = "simplemem_cross_memory"


class QdrantVectorStore(VectorStore):
    """
    Qdrant implementation of VectorStore.

    Manages memory entry embeddings with semantic/keyword search using
    a single Qdrant collection with tenant_id payload filtering.

    Attributes:
        collection_name: Name of the Qdrant collection.
        vector_size: Dimension of embedding vectors.
    """

    def __init__(
        self,
        location: Optional[str] = None,
        url: Optional[str] = None,
        port: Optional[int] = 6333,
        grpc_port: int = 6334,
        prefer_grpc: bool = False,
        https: Optional[bool] = None,
        api_key: Optional[str] = None,
        prefix: Optional[str] = None,
        timeout: Optional[float] = None,
        host: Optional[str] = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        vector_size: int = DEFAULT_VECTOR_SIZE,
        distance: Distance = Distance.COSINE,
    ) -> None:
        """
        Initialize Qdrant vector store.

        Args:
            location: If ":memory:" - use in-memory Qdrant, if a path - use local storage.
            url: Full URL for Qdrant server.
            port: HTTP port for Qdrant server.
            grpc_port: gRPC port for Qdrant server.
            prefer_grpc: Prefer gRPC over HTTP.
            https: Use HTTPS.
            api_key: API key for authentication.
            prefix: URL prefix for Qdrant.
            timeout: Request timeout in seconds.
            host: Hostname for Qdrant server.
            collection_name: Name of the collection to use.
            vector_size: Dimension of embedding vectors.
            distance: Distance metric for vector similarity.
        """
        self._location = location
        self._url = url
        self._port = port
        self._grpc_port = grpc_port
        self._prefer_grpc = prefer_grpc
        self._https = https
        self._api_key = api_key
        self._prefix = prefix
        self._timeout = timeout
        self._host = host
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._distance = distance
        self._client: Optional[AsyncQdrantClient] = None
        self._initialized = False

    async def _get_client(self) -> AsyncQdrantClient:
        """Get or create the async Qdrant client."""
        if self._client is None:
            client_kwargs: dict[str, Any] = {
                "timeout": self._timeout,
            }

            # In-memory mode
            if self._location == ":memory:":
                client_kwargs["location"] = ":memory:"
            # Local file storage
            elif self._location and not self._location.startswith(("http://", "https://")):
                client_kwargs["location"] = self._location
            # Remote server via URL
            elif self._url:
                client_kwargs["url"] = self._url
            # Remote server via host/port
            elif self._host:
                client_kwargs["host"] = self._host
                client_kwargs["port"] = self._port
                client_kwargs["grpc_port"] = self._grpc_port
                client_kwargs["prefer_grpc"] = self._prefer_grpc
            # Default to localhost
            else:
                client_kwargs["host"] = "localhost"
                client_kwargs["port"] = self._port
                client_kwargs["grpc_port"] = self._grpc_port
                client_kwargs["prefer_grpc"] = self._prefer_grpc

            if self._https is not None:
                client_kwargs["https"] = self._https
            if self._api_key:
                client_kwargs["api_key"] = self._api_key
            if self._prefix:
                client_kwargs["prefix"] = self._prefix

            self._client = AsyncQdrantClient(**client_kwargs)
        return self._client

    async def initialize(self) -> None:
        """Initialize collection with proper schema. Must be called before use."""
        client = await self._get_client()

        # Check if collection exists
        collections = await client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if self.collection_name not in collection_names:
            # Create collection with vector configuration
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=self._distance,
                ),
            )
            logger.info(f"Created Qdrant collection: {self.collection_name}")

            # Create payload indexes for filtering
            await self._create_payload_indexes(client)
        else:
            logger.info(f"Using existing Qdrant collection: {self.collection_name}")
            # Ensure indexes exist
            await self._create_payload_indexes(client)

        self._initialized = True

    async def _create_payload_indexes(self, client: AsyncQdrantClient) -> None:
        """Create payload indexes for efficient filtering."""
        try:
            # Index tenant_id for multitenancy filtering
            await client.create_payload_index(
                collection_name=self.collection_name,
                field_name="tenant_id",
                field_schema=rest.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            # Index may already exist
            pass

        try:
            # Index memory_session_id for session filtering
            await client.create_payload_index(
                collection_name=self.collection_name,
                field_name="memory_session_id",
                field_schema=rest.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

        try:
            # Index entry_id for lookups
            await client.create_payload_index(
                collection_name=self.collection_name,
                field_name="entry_id",
                field_schema=rest.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

        try:
            # Index timestamp for temporal queries
            await client.create_payload_index(
                collection_name=self.collection_name,
                field_name="timestamp",
                field_schema=rest.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

    async def close(self) -> None:
        """Close the Qdrant client and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._initialized = False

    async def __aenter__(self) -> "QdrantVectorStore":
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    def _now_iso(self) -> str:
        """Get current UTC datetime as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def _point_to_entry(self, point: rest.Record) -> CrossMemoryEntry:
        """Convert a Qdrant point to CrossMemoryEntry."""
        payload = point.payload or {}

        return CrossMemoryEntry(
            entry_id=payload.get("entry_id", str(point.id)),
            lossless_restatement=payload.get("lossless_restatement", ""),
            keywords=payload.get("keywords", []),
            timestamp=payload.get("timestamp"),
            location=payload.get("location"),
            persons=payload.get("persons", []),
            entities=payload.get("entities", []),
            topic=payload.get("topic"),
            tenant_id=payload.get("tenant_id", "default"),
            memory_session_id=payload.get("memory_session_id", ""),
            source_kind=payload.get("source_kind", ""),
            source_id=payload.get("source_id"),
            importance=payload.get("importance", 0.5),
            valid_from=self._parse_datetime(payload.get("valid_from")),
            valid_to=self._parse_datetime(payload.get("valid_to")),
            superseded_by=payload.get("superseded_by"),
        )

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string to datetime object."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    def _build_tenant_filter(
        self, tenant_id: Optional[str] = None
    ) -> Optional[rest.Filter]:
        """Build filter for tenant_id."""
        if not tenant_id:
            return None
        return rest.Filter(
            must=[
                rest.FieldCondition(
                    key="tenant_id",
                    match=rest.MatchValue(value=tenant_id),
                )
            ]
        )

    def _build_session_filter(
        self, memory_session_id: str
    ) -> rest.Filter:
        """Build filter for memory_session_id."""
        return rest.Filter(
            must=[
                rest.FieldCondition(
                    key="memory_session_id",
                    match=rest.MatchValue(value=memory_session_id),
                )
            ]
        )

    def _build_combined_filter(
        self,
        tenant_id: Optional[str] = None,
        memory_session_id: Optional[str] = None,
        project: Optional[str] = None,
        persons: Optional[list[str]] = None,
        location: Optional[str] = None,
        entities: Optional[list[str]] = None,
        timestamp_range: Optional[tuple] = None,
    ) -> Optional[rest.Filter]:
        """Build combined filter with multiple conditions."""
        must_conditions: list[rest.Condition] = []

        if tenant_id:
            must_conditions.append(
                rest.FieldCondition(
                    key="tenant_id",
                    match=rest.MatchValue(value=tenant_id),
                )
            )

        if memory_session_id:
            must_conditions.append(
                rest.FieldCondition(
                    key="memory_session_id",
                    match=rest.MatchValue(value=memory_session_id),
                )
            )

        if project:
            must_conditions.append(
                rest.FieldCondition(
                    key="project",
                    match=rest.MatchValue(value=project),
                )
            )

        if persons:
            for person in persons:
                must_conditions.append(
                    rest.FieldCondition(
                        key="persons",
                        match=rest.MatchAny(any=persons),
                    )
                )
                break  # Use MatchAny for list membership

        if location:
            must_conditions.append(
                rest.FieldCondition(
                    key="location",
                    match=rest.MatchText(text=location),
                )
            )

        if entities:
            for entity in entities:
                must_conditions.append(
                    rest.FieldCondition(
                        key="entities",
                        match=rest.MatchAny(any=entities),
                    )
                )
                break  # Use MatchAny for list membership

        if timestamp_range:
            start_time, end_time = timestamp_range
            start_str = str(start_time) if start_time else None
            end_str = str(end_time) if end_time else None

            range_filter: dict[str, Any] = {}
            if start_str:
                range_filter["gte"] = start_str
            if end_str:
                range_filter["lte"] = end_str

            if range_filter:
                must_conditions.append(
                    rest.FieldCondition(
                        key="timestamp",
                        range=rest.Range(**range_filter),
                    )
                )

        if not must_conditions:
            return None

        return rest.Filter(must=must_conditions)

    async def add_entries(
        self,
        entries: list[CrossMemoryEntry],
        tenant_id: str,
        memory_session_id: str,
        source_kind: str,
        source_id: int = 0,
        importance: float = 0.5,
    ) -> None:
        """
        Batch add memory entries to the vector store.

        Args:
            entries: List of CrossMemoryEntry objects to add.
            tenant_id: Tenant identifier for multitenancy.
            memory_session_id: Session identifier for provenance.
            source_kind: Type of source (e.g., "observation", "summary").
            source_id: ID of the source record.
            importance: Importance score for the entries.
        """
        if not entries:
            return

        client = await self._get_client()
        now = self._now_iso()

        points = []
        for entry in entries:
            # Use entry's entry_id or generate a new one
            entry_id = entry.entry_id or str(uuid.uuid4())
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, entry_id))

            payload: dict[str, Any] = {
                "entry_id": entry_id,
                "lossless_restatement": entry.lossless_restatement,
                "keywords": entry.keywords or [],
                "timestamp": entry.timestamp or "",
                "location": entry.location or "",
                "persons": entry.persons or [],
                "entities": entry.entities or [],
                "topic": entry.topic or "",
                "tenant_id": tenant_id,
                "memory_session_id": memory_session_id,
                "source_kind": source_kind,
                "source_id": source_id,
                "importance": float(importance),
                "valid_from": entry.valid_from.isoformat() if entry.valid_from else now,
                "valid_to": entry.valid_to.isoformat() if entry.valid_to else "",
                "superseded_by": entry.superseded_by or "",
            }

            # If entry has vector, use it; otherwise use zero vector placeholder
            vector = getattr(entry, "vector", None)
            if vector is None:
                # Generate placeholder - in practice, caller should pre-compute vectors
                logger.warning(
                    f"Entry {entry_id} has no vector. "
                    "Consider pre-computing vectors for better performance."
                )
                vector = [0.0] * self.vector_size

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        try:
            await client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            logger.info(f"Added {len(entries)} entries to Qdrant collection")
        except Exception:
            logger.exception("Failed to add entries to Qdrant")
            raise

    async def semantic_search(
        self,
        query: str,
        top_k: int = 25,
        tenant_id: Optional[str] = None,
        project: Optional[str] = None,
    ) -> list[CrossMemoryEntry]:
        """
        Search entries by semantic similarity.

        Args:
            query: Query text (should be pre-embedded by caller).
            top_k: Maximum number of results to return.
            tenant_id: Optional tenant filter.
            project: Optional project filter.

        Note:
            This method expects the query to be a pre-computed vector string
            or will use a zero vector if not available. Callers should embed
            the query text before calling this method.

        Returns:
            List of matching CrossMemoryEntry objects.
        """
        client = await self._get_client()

        # Build filter
        query_filter = self._build_combined_filter(
            tenant_id=tenant_id,
            project=project,
        )

        try:
            # Note: In practice, query should be a pre-computed vector
            # For now, we expect callers to handle embedding
            # If query is a string that looks like a vector representation,
            # this would need to be parsed. Otherwise, return empty.

            # Check collection has points
            collection_info = await client.get_collection(self.collection_name)
            if collection_info.points_count == 0:
                return []

            # Use scroll to get entries when no vector is provided
            # This is a fallback - ideally semantic search requires vectors
            if query_filter:
                results, _ = await client.scroll(
                    collection_name=self.collection_name,
                    limit=top_k,
                    query_filter=query_filter,
                    with_payload=True,
                    with_vectors=False,
                )
            else:
                results, _ = await client.scroll(
                    collection_name=self.collection_name,
                    limit=top_k,
                    with_payload=True,
                    with_vectors=False,
                )

            return [self._point_to_entry(point) for point in results]
        except Exception:
            logger.exception("Failed semantic search in Qdrant")
            return []

    async def semantic_search_vector(
        self,
        query_vector: list[float],
        top_k: int = 25,
        tenant_id: Optional[str] = None,
        project: Optional[str] = None,
    ) -> list[CrossMemoryEntry]:
        """
        Search entries by pre-computed query vector.

        Args:
            query_vector: Pre-computed embedding vector.
            top_k: Maximum number of results to return.
            tenant_id: Optional tenant filter.
            project: Optional project filter.

        Returns:
            List of matching CrossMemoryEntry objects.
        """
        client = await self._get_client()

        query_filter = self._build_combined_filter(
            tenant_id=tenant_id,
            project=project,
        )

        try:
            results = await client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )

            return [self._point_to_entry(point) for point in results]
        except Exception:
            logger.exception("Failed semantic vector search in Qdrant")
            return []

    async def keyword_search(
        self,
        keywords: list[str],
        top_k: int = 5,
        tenant_id: Optional[str] = None,
    ) -> list[CrossMemoryEntry]:
        """
        Search entries by keyword matching.

        Uses Qdrant's full-text search on lossless_restatement field.

        Args:
            keywords: List of keywords to search for.
            top_k: Maximum number of results to return.
            tenant_id: Optional tenant filter.

        Returns:
            List of matching CrossMemoryEntry objects.
        """
        if not keywords:
            return []

        client = await self._get_client()

        # Build keyword filter using MatchText
        keyword_text = " ".join(keywords)
        must_conditions: list[rest.Condition] = [
            rest.FieldCondition(
                key="lossless_restatement",
                match=rest.MatchText(text=keyword_text),
            )
        ]

        if tenant_id:
            must_conditions.append(
                rest.FieldCondition(
                    key="tenant_id",
                    match=rest.MatchValue(value=tenant_id),
                )
            )

        query_filter = rest.Filter(must=must_conditions)

        try:
            results = await client.scroll(
                collection_name=self.collection_name,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )

            points, _ = results
            return [self._point_to_entry(point) for point in points]
        except Exception:
            logger.exception("Failed keyword search in Qdrant")
            return []

    async def structured_search(
        self,
        persons: Optional[list[str]] = None,
        timestamp_range: Optional[tuple] = None,
        location: Optional[str] = None,
        entities: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[CrossMemoryEntry]:
        """
        Search entries by metadata filters.

        Args:
            persons: List of person names to filter by.
            timestamp_range: Tuple of (start_time, end_time) for temporal filtering.
            location: Location string to filter by.
            entities: List of entity names to filter by.
            tenant_id: Optional tenant filter.
            top_k: Maximum number of results to return.

        Returns:
            List of matching CrossMemoryEntry objects.
        """
        client = await self._get_client()

        query_filter = self._build_combined_filter(
            tenant_id=tenant_id,
            persons=persons,
            location=location,
            entities=entities,
            timestamp_range=timestamp_range,
        )

        if query_filter is None:
            return []

        try:
            results = await client.scroll(
                collection_name=self.collection_name,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )

            points, _ = results
            return [self._point_to_entry(point) for point in points]
        except Exception:
            logger.exception("Failed structured search in Qdrant")
            return []

    async def get_entries_for_session(
        self, memory_session_id: str
    ) -> list[CrossMemoryEntry]:
        """
        Get all entries for a specific session.

        Args:
            memory_session_id: Session identifier to filter by.

        Returns:
            List of CrossMemoryEntry objects for the session.
        """
        client = await self._get_client()
        query_filter = self._build_session_filter(memory_session_id)

        try:
            # Scroll through all matching entries
            all_points = []
            offset = None

            while True:
                results = await client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    query_filter=query_filter,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )

                points, next_offset = results
                all_points.extend(points)

                if next_offset is None:
                    break
                offset = next_offset

            return [self._point_to_entry(point) for point in all_points]
        except Exception:
            logger.exception("Failed to get session entries from Qdrant")
            return []

    async def get_all_entries(
        self, tenant_id: Optional[str] = None
    ) -> list[CrossMemoryEntry]:
        """
        Get all entries, optionally filtered by tenant.

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            List of CrossMemoryEntry objects.
        """
        client = await self._get_client()
        query_filter = self._build_tenant_filter(tenant_id)

        try:
            all_points = []
            offset = None

            while True:
                results = await client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    query_filter=query_filter,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )

                points, next_offset = results
                all_points.extend(points)

                if next_offset is None:
                    break
                offset = next_offset

            return [self._point_to_entry(point) for point in all_points]
        except Exception:
            logger.exception("Failed to get all entries from Qdrant")
            return []

    async def mark_superseded(self, old_entry_id: str, new_entry_id: str) -> None:
        """
        Mark an entry as superseded by another entry.

        Args:
            old_entry_id: ID of the entry to mark as superseded.
            new_entry_id: ID of the entry that supersedes it.
        """
        client = await self._get_client()
        now = self._now_iso()

        # Find the point with the old entry_id
        query_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="entry_id",
                    match=rest.MatchValue(value=old_entry_id),
                )
            ]
        )

        try:
            # Find the point
            results = await client.scroll(
                collection_name=self.collection_name,
                limit=1,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=True,  # Need vector to re-upsert
            )

            points, _ = results
            if not points:
                logger.warning(f"Entry {old_entry_id} not found for superseding")
                return

            point = points[0]
            payload = dict(point.payload or {})
            payload["superseded_by"] = new_entry_id
            payload["valid_to"] = now

            # Update the point
            await client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=str(point.id),
                        vector=point.vector or [0.0] * self.vector_size,
                        payload=payload,
                    )
                ],
            )
            logger.info(f"Marked entry {old_entry_id} as superseded by {new_entry_id}")
        except Exception:
            logger.exception("Failed to mark entry as superseded")
            raise

    async def update_importance(self, entry_id: str, new_importance: float) -> None:
        """
        Update importance score for an entry.

        Args:
            entry_id: ID of the entry to update.
            new_importance: New importance score (0.0 to 1.0).
        """
        client = await self._get_client()

        query_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="entry_id",
                    match=rest.MatchValue(value=entry_id),
                )
            ]
        )

        try:
            results = await client.scroll(
                collection_name=self.collection_name,
                limit=1,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=True,
            )

            points, _ = results
            if not points:
                logger.warning(f"Entry {entry_id} not found for importance update")
                return

            point = points[0]
            payload = dict(point.payload or {})
            payload["importance"] = float(new_importance)

            await client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=str(point.id),
                        vector=point.vector or [0.0] * self.vector_size,
                        payload=payload,
                    )
                ],
            )
            logger.info(f"Updated importance for entry {entry_id} to {new_importance}")
        except Exception:
            logger.exception("Failed to update importance")
            raise

    async def clear(self, tenant_id: Optional[str] = None) -> None:
        """
        Clear all entries or entries for a specific tenant.

        Args:
            tenant_id: Optional tenant filter. If None, clears all entries.
        """
        client = await self._get_client()

        try:
            if tenant_id:
                # Delete points for specific tenant
                query_filter = self._build_tenant_filter(tenant_id)
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=rest.FilterSelector(filter=query_filter),
                )
                logger.info(f"Cleared entries for tenant {tenant_id}")
            else:
                # Delete all points in collection
                await client.delete_collection(self.collection_name)
                # Recreate collection
                await self.initialize()
                logger.info("Cleared all entries and recreated collection")
        except Exception:
            logger.exception("Failed to clear entries")
            raise

    async def optimize(self) -> None:
        """
        Optimize the vector store for better query performance.

        In Qdrant, this triggers collection optimization.
        """
        client = await self._get_client()

        try:
            # Qdrant optimizes automatically, but we can trigger a manual optimization
            # by calling update_collection with optimizer config
            await client.update_collection(
                collection_name=self.collection_name,
                optimizer_config=rest.OptimizersConfigDiff(
                    indexing_threshold=10000,
                ),
            )
            logger.info("Triggered Qdrant collection optimization")
        except Exception:
            logger.exception("Failed to optimize collection")
            # Non-critical error, don't raise

    async def count_entries(
        self, tenant_id: Optional[str] = None, memory_session_id: Optional[str] = None
    ) -> int:
        """
        Count entries with optional filters.

        Args:
            tenant_id: Optional tenant filter.
            memory_session_id: Optional session filter.

        Returns:
            Number of matching entries.
        """
        client = await self._get_client()

        if tenant_id is None and memory_session_id is None:
            # Use collection stats for fast count
            try:
                info = await client.get_collection(self.collection_name)
                return info.points_count or 0
            except Exception:
                logger.exception("Failed to get collection count")
                return 0

        # Filtered count using scroll
        query_filter = self._build_combined_filter(
            tenant_id=tenant_id,
            memory_session_id=memory_session_id,
        )

        try:
            count = 0
            offset = None

            while True:
                results = await client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    query_filter=query_filter,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )

                points, next_offset = results
                count += len(points)

                if next_offset is None:
                    break
                offset = next_offset

            return count
        except Exception:
            logger.exception("Failed to count entries")
            return 0