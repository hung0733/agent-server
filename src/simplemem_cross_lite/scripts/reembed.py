#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportMissingParameterType=false
"""
Re-embedding script for SimpleMem-Cross-Lite.

This script re-embeds all vector entries when embedding dimensions change,
supporting batch processing, tenant filtering, and resume capability.

Usage:
    python -m simplemem_cross_lite.scripts.reembed --help
    python scripts/reembed.py --tenant-id my-tenant --batch-size 50 --progress
    python scripts/reembed.py --dry-run
    python scripts/reembed.py --resume --run-id abc123
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING or __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simplemem_cross_lite.clients.embedding import EmbeddingClient
    from simplemem_cross_lite.storage.postgres import PostgresSessionStorage
    from simplemem_cross_lite.storage.qdrant import QdrantVectorStore
    from simplemem_cross_lite.types import CrossMemoryEntry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ReembedProgress:
    """Tracks re-embedding progress in PostgreSQL for resume capability."""

    TABLE_NAME = "reembed_progress"

    def __init__(self, pg_storage: PostgresSessionStorage):
        self.pg_storage = pg_storage

    async def ensure_table(self) -> None:
        """Create progress tracking table if not exists."""
        pool = await self.pg_storage._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    total_entries INTEGER DEFAULT 0,
                    processed_entries INTEGER DEFAULT 0,
                    failed_entries INTEGER DEFAULT 0,
                    last_entry_id TEXT,
                    config_json JSONB,
                    completed_at TIMESTAMPTZ
                )
                """
            )

    async def create_run(
        self,
        run_id: str,
        tenant_id: Optional[str],
        config: dict,
        total_entries: int,
    ) -> None:
        """Create a new progress tracking record."""
        pool = await self.pg_storage._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    run_id, tenant_id, started_at, status, total_entries, config_json
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                run_id,
                tenant_id or "all",
                datetime.now(timezone.utc),
                "running",
                total_entries,
                json.dumps(config),
            )

    async def update_progress(
        self,
        run_id: str,
        processed: int,
        failed: int,
        last_entry_id: str,
    ) -> None:
        """Update progress for a running job."""
        pool = await self.pg_storage._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {self.TABLE_NAME}
                SET processed_entries = $1,
                    failed_entries = $2,
                    last_entry_id = $3
                WHERE run_id = $4
                """,
                processed,
                failed,
                last_entry_id,
                run_id,
            )

    async def complete_run(self, run_id: str, status: str = "completed") -> None:
        """Mark a run as completed."""
        pool = await self.pg_storage._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {self.TABLE_NAME}
                SET status = $1, completed_at = $2
                WHERE run_id = $3
                """,
                status,
                datetime.now(timezone.utc),
                run_id,
            )

    async def get_run(self, run_id: str) -> Optional[dict]:
        """Get progress for a specific run."""
        pool = await self.pg_storage._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.TABLE_NAME} WHERE run_id = $1",
                run_id,
            )
            return dict(row) if row else None

    async def get_last_entry_id(self, run_id: str) -> Optional[str]:
        """Get the last processed entry ID for resume."""
        run = await self.get_run(run_id)
        if run and run.get("last_entry_id"):
            return run["last_entry_id"]
        return None


class ReembedStats:
    """Statistics for a re-embedding run."""

    def __init__(self):
        self.total_entries = 0
        self.processed = 0
        self.failed = 0
        self.skipped = 0
        self.batches = 0

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "processed": self.processed,
            "failed": self.failed,
            "skipped": self.skipped,
            "batches": self.batches,
        }


async def fetch_entries_batch(
    vector_store: QdrantVectorStore,
    tenant_id: Optional[str],
    batch_size: int,
    offset: int = 0,
) -> list[CrossMemoryEntry]:
    """
    Fetch a batch of entries from the vector store.

    Uses pagination to avoid loading all entries into memory.
    """
    # QdrantVectorStore.get_all_entries doesn't support pagination,
    # so we use scroll internally
    client = await vector_store._get_client()

    # Build filter
    if tenant_id:
        from qdrant_client.http import models as rest
        query_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="tenant_id",
                    match=rest.MatchValue(value=tenant_id),
                )
            ]
        )
    else:
        query_filter = None

    try:
        from qdrant_client.http import models as rest

        # Use scroll to get entries with pagination
        results = await client.scroll(
            collection_name=vector_store.collection_name,
            limit=batch_size,
            offset=offset,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=True,  # Need vectors to compare dimensions
        )

        points, _ = results

        entries = []
        for point in points:
            payload = point.payload or {}
            entry = CrossMemoryEntry(
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
                valid_from=parse_datetime(payload.get("valid_from")),
                valid_to=parse_datetime(payload.get("valid_to")),
                superseded_by=payload.get("superseded_by"),
            )
            # Attach the vector for dimension checking
            if point.vector:
                entry._vector = point.vector  # type: ignore[attr-defined]
            entries.append(entry)

        return entries
    except Exception:
        logger.exception("Failed to fetch entries batch")
        return []


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string to datetime object."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def update_entry_vector(
    vector_store: QdrantVectorStore,
    entry_id: str,
    new_vector: list[float],
    new_payload: dict,
) -> bool:
    """
    Update a single entry with a new vector.

    Returns True if successful, False otherwise.
    """
    import uuid
    from qdrant_client.http import models as rest
    from qdrant_client.http.models import PointStruct

    client = await vector_store._get_client()

    # Find the point ID for this entry
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
            collection_name=vector_store.collection_name,
            limit=1,
            query_filter=query_filter,
            with_payload=False,
            with_vectors=False,
        )

        points, _ = results
        if not points:
            logger.warning(f"Entry {entry_id} not found for update")
            return False

        point_id = points[0].id

        # Update with new vector
        await client.upsert(
            collection_name=vector_store.collection_name,
            points=[
                PointStruct(
                    id=str(point_id),
                    vector=new_vector,
                    payload=new_payload,
                )
            ],
        )
        return True
    except Exception:
        logger.exception(f"Failed to update vector for entry {entry_id}")
        return False


async def reembed_entries(
    vector_store: QdrantVectorStore,
    embedding_client: EmbeddingClient,
    tenant_id: Optional[str],
    batch_size: int,
    dry_run: bool,
    progress: Optional[ReembedProgress],
    run_id: Optional[str],
    show_progress: bool,
    expected_dimension: Optional[int],
) -> ReembedStats:
    """
    Re-embed all entries matching the filter criteria.

    Args:
        vector_store: Qdrant vector store instance
        embedding_client: Embedding client for generating new vectors
        tenant_id: Optional tenant filter
        batch_size: Number of entries to process per batch
        dry_run: If True, don't actually update vectors
        progress: Progress tracker for resume capability
        run_id: Run ID for resuming
        show_progress: If True, print progress updates
        expected_dimension: If set, only re-embed entries with different dimensions

    Returns:
        ReembedStats with processing statistics
    """
    stats = ReembedStats()

    # Count total entries
    total_count = await vector_store.count_entries(tenant_id=tenant_id)
    stats.total_entries = total_count

    if show_progress:
        logger.info(f"Found {total_count} entries to process")

    if total_count == 0:
        logger.info("No entries found. Nothing to re-embed.")
        return stats

    # Get last processed entry ID if resuming
    last_processed_id: Optional[str] = None
    if progress and run_id:
        run_data = await progress.get_run(run_id)
        if run_data and run_data.get("status") == "running":
            last_processed_id = run_data.get("last_entry_id")
            stats.processed = run_data.get("processed_entries", 0)
            stats.failed = run_data.get("failed_entries", 0)
            if show_progress:
                logger.info(f"Resuming from entry after {last_processed_id}, "
                           f"already processed: {stats.processed}")

    offset = 0
    if last_processed_id:
        # Find the offset for the last processed entry
        # This is approximate - we'll skip entries until we find the last one
        offset = stats.processed

    continue_from_last = last_processed_id is not None

    while True:
        # Fetch batch
        entries = await fetch_entries_batch(
            vector_store, tenant_id, batch_size, offset
        )

        if not entries:
            break

        # If resuming, skip entries until we find the last processed one
        if continue_from_last and last_processed_id:
            found_last = False
            for i, entry in enumerate(entries):
                if entry.entry_id == last_processed_id:
                    entries = entries[i + 1:]
                    found_last = True
                    break
            if not found_last:
                # Continue to next batch
                offset += batch_size
                continue
            continue_from_last = False

        stats.batches += 1

        # Process batch
        for entry in entries:
            # Check dimension if specified
            entry_vector = getattr(entry, "_vector", None)
            if expected_dimension is not None and entry_vector is not None:
                current_dim = len(entry_vector)
                if current_dim == expected_dimension:
                    stats.skipped += 1
                    continue

            try:
                if not dry_run:
                    # Generate new embedding
                    new_vector = await embedding_client.create_single_embedding(
                        entry.lossless_restatement
                    )

                    # Build payload
                    payload = {
                        "entry_id": entry.entry_id,
                        "lossless_restatement": entry.lossless_restatement,
                        "keywords": entry.keywords or [],
                        "timestamp": entry.timestamp or "",
                        "location": entry.location or "",
                        "persons": entry.persons or [],
                        "entities": entry.entities or [],
                        "topic": entry.topic or "",
                        "tenant_id": entry.tenant_id,
                        "memory_session_id": entry.memory_session_id,
                        "source_kind": entry.source_kind,
                        "source_id": entry.source_id,
                        "importance": entry.importance,
                        "valid_from": (entry.valid_from.isoformat()
                                       if entry.valid_from else ""),
                        "valid_to": (entry.valid_to.isoformat()
                                    if entry.valid_to else ""),
                        "superseded_by": entry.superseded_by or "",
                    }

                    # Update the entry
                    success = await update_entry_vector(
                        vector_store, entry.entry_id, new_vector, payload
                    )

                    if success:
                        stats.processed += 1
                    else:
                        stats.failed += 1
                else:
                    # Dry run - just count
                    stats.processed += 1

                # Update progress
                if progress and run_id and not dry_run:
                    await progress.update_progress(
                        run_id, stats.processed, stats.failed, entry.entry_id
                    )

                if show_progress and stats.processed % 10 == 0:
                    pct = (stats.processed / stats.total_entries * 100
                           if stats.total_entries > 0 else 0)
                    logger.info(f"Progress: {stats.processed}/{stats.total_entries} "
                               f"({pct:.1f}%), failed: {stats.failed}")

            except Exception as e:
                logger.error(f"Failed to re-embed entry {entry.entry_id}: {e}")
                stats.failed += 1

        offset += batch_size

        # Check if we've processed all entries
        if len(entries) < batch_size:
            break

    return stats


async def main_async(args: argparse.Namespace) -> int:
    """Main async entry point."""
    # Initialize storage clients
    pg_dsn = args.pg_dsn or os.environ.get(
        "DATABASE_URL", "postgresql://localhost/simplemem"
    )
    qdrant_url = args.qdrant_url or os.environ.get(
        "QDRANT_URL", "http://localhost:6333"
    )
    qdrant_api_key = args.qdrant_api_key or os.environ.get("QDRANT_API_KEY")
    embedding_api_key = args.embedding_api_key or os.environ.get(
        "OPENAI_API_KEY"
    )
    embedding_model = args.embedding_model or os.environ.get(
        "EMBEDDING_MODEL", "text-embedding-3-small"
    )
    embedding_base_url = args.embedding_base_url or os.environ.get(
        "EMBEDDING_BASE_URL", "https://api.openai.com/v1"
    )

    if not embedding_api_key:
        logger.error(
            "Embedding API key required. Set OPENAI_API_KEY or use --embedding-api-key"
        )
        return 1

    # Initialize clients
    pg_storage = PostgresSessionStorage(dsn=pg_dsn)
    vector_store = QdrantVectorStore(
        url=qdrant_url,
        api_key=qdrant_api_key,
        vector_size=args.vector_size,
    )
    embedding_client = EmbeddingClient(
        api_key=embedding_api_key,
        base_url=embedding_base_url,
        model=embedding_model,
    )

    try:
        # Initialize connections
        await pg_storage.initialize()
        await vector_store.initialize()

        # Ensure progress table exists
        progress = ReembedProgress(pg_storage)
        await progress.ensure_table()

        # Handle resume
        run_id = args.run_id
        if args.resume and not run_id:
            # List recent runs
            pool = await pg_storage._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT run_id, status, started_at, processed_entries, total_entries
                    FROM {progress.TABLE_NAME}
                    WHERE status = 'running'
                    ORDER BY started_at DESC
                    LIMIT 5
                    """
                )
                if rows:
                    logger.info("Recent incomplete runs:")
                    for row in rows:
                        logger.info(
                            f"  - {row['run_id']}: {row['processed_entries']}/"
                            f"{row['total_entries']} entries, started "
                            f"{row['started_at']}"
                        )
                    logger.info("Use --run-id <id> to resume a specific run")
                    return 0
                else:
                    logger.info("No incomplete runs found to resume")
                    return 0

        # Generate new run ID if not resuming
        if not run_id:
            run_id = str(uuid.uuid4())[:8]

        config = {
            "tenant_id": args.tenant_id,
            "batch_size": args.batch_size,
            "dry_run": args.dry_run,
            "embedding_model": embedding_model,
            "expected_dimension": args.expected_dimension,
        }

        logger.info(f"Starting re-embedding run: {run_id}")
        logger.info(f"Config: {json.dumps(config, indent=2)}")

        # Count entries
        total = await vector_store.count_entries(tenant_id=args.tenant_id)
        if args.dry_run:
            logger.info(f"[DRY RUN] Would process {total} entries")
        else:
            # Create progress record
            await progress.create_run(run_id, args.tenant_id, config, total)

        # Run re-embedding
        stats = await reembed_entries(
            vector_store=vector_store,
            embedding_client=embedding_client,
            tenant_id=args.tenant_id,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            progress=progress,
            run_id=run_id,
            show_progress=args.progress,
            expected_dimension=args.expected_dimension,
        )

        # Mark as complete
        if not args.dry_run:
            final_status = "completed" if stats.failed == 0 else "completed_with_errors"
            await progress.complete_run(run_id, final_status)

        # Print summary
        logger.info(f"Re-embedding complete: {json.dumps(stats.to_dict(), indent=2)}")

        return 0 if stats.failed == 0 else 1

    except Exception as e:
        logger.exception(f"Re-embedding failed: {e}")
        return 1
    finally:
        # Cleanup
        await pg_storage.close()
        await vector_store.close()
        await embedding_client.close()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Re-embed vector entries in SimpleMem-Cross-Lite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Re-embed all entries with progress
  python scripts/reembed.py --progress

  # Re-embed entries for a specific tenant
  python scripts/reembed.py --tenant-id my-tenant --batch-size 50

  # Dry run to see what would happen
  python scripts/reembed.py --dry-run

  # Resume an interrupted run
  python scripts/reembed.py --resume --run-id abc123

  # Only re-embed entries with wrong dimension
  python scripts/reembed.py --expected-dimension 1024

Environment variables:
  DATABASE_URL         PostgreSQL connection string
  QDRANT_URL           Qdrant server URL
  QDRANT_API_KEY       Qdrant API key
  OPENAI_API_KEY       Embedding API key
  EMBEDDING_MODEL      Embedding model (default: text-embedding-3-small)
  EMBEDDING_BASE_URL   Embedding API base URL
        """,
    )

    # Filter options
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Filter by tenant ID (default: all tenants)",
    )
    parser.add_argument(
        "--expected-dimension",
        type=int,
        default=None,
        help="Only re-embed entries with different vector dimensions",
    )

    # Batch options
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of entries to process per batch (default: 100)",
    )
    parser.add_argument(
        "--vector-size",
        type=int,
        default=1536,
        help="Expected vector dimension for new embeddings (default: 1536)",
    )

    # Progress and resume
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress updates during processing",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted run",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Specific run ID to resume",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )

    # Connection options
    parser.add_argument(
        "--pg-dsn",
        type=str,
        default=None,
        help="PostgreSQL connection string (or set DATABASE_URL)",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=None,
        help="Qdrant server URL (or set QDRANT_URL)",
    )
    parser.add_argument(
        "--qdrant-api-key",
        type=str,
        default=None,
        help="Qdrant API key (or set QDRANT_API_KEY)",
    )
    parser.add_argument(
        "--embedding-api-key",
        type=str,
        default=None,
        help="Embedding API key (or set OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=None,
        help="Embedding model name",
    )
    parser.add_argument(
        "--embedding-base-url",
        type=str,
        default=None,
        help="Embedding API base URL",
    )

    args = parser.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())