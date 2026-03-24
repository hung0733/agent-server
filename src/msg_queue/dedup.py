"""Duplicate message filter with TTL-based expiry.

Prevents the same message (by ID) from being processed more than once,
even when Evolution API delivers duplicate WebSocket events (e.g. after
reconnection or network hiccup).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from i18n import _

logger = logging.getLogger(__name__)


class MessageDeduplicator:
    """TTL-based in-memory deduplication store.

    Tracks message IDs for a configurable window (default 300 s).
    Expired entries are purged on every ``register`` call to bound memory usage.

    Args:
        ttl_seconds: How long a message ID is considered "seen".
                     Reads ``DEDUP_TTL_SECONDS`` env var if not provided.
    """

    def __init__(self, ttl_seconds: float | None = None) -> None:
        if ttl_seconds is None:
            ttl_seconds = float(os.getenv("DEDUP_TTL_SECONDS", "300"))
        self._ttl = timedelta(seconds=ttl_seconds)
        self._seen: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def is_duplicate(self, msg_id: str) -> bool:
        """Return True if *msg_id* was registered within the TTL window."""
        async with self._lock:
            seen_at = self._seen.get(msg_id)
            if seen_at is None:
                return False
            if datetime.now(timezone.utc).replace(tzinfo=None) - seen_at < self._ttl:
                return True
            # Entry expired — treat as new and remove stale record
            del self._seen[msg_id]
            return False

    async def register(self, msg_id: str) -> None:
        """Mark *msg_id* as seen and purge expired entries."""
        async with self._lock:
            self._seen[msg_id] = datetime.now(timezone.utc).replace(tzinfo=None)
            self._purge_expired()

    def _purge_expired(self) -> None:
        """Remove entries older than TTL. Called under lock."""
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - self._ttl
        expired = [k for k, v in self._seen.items() if v < cutoff]
        for k in expired:
            del self._seen[k]
        if expired:
            logger.debug(_("Dedup: purged %d expired entries"), len(expired))

    @property
    def size(self) -> int:
        """Current number of tracked message IDs."""
        return len(self._seen)
