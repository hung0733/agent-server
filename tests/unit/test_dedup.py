"""Unit tests for MessageDeduplicator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from msg_queue.dedup import MessageDeduplicator


class TestMessageDeduplicator:

    async def test_new_message_not_duplicate(self):
        dedup = MessageDeduplicator(ttl_seconds=60)
        assert await dedup.is_duplicate("msg-001") is False

    async def test_registered_message_is_duplicate(self):
        dedup = MessageDeduplicator(ttl_seconds=60)
        await dedup.register("msg-001")
        assert await dedup.is_duplicate("msg-001") is True

    async def test_different_ids_not_duplicate(self):
        dedup = MessageDeduplicator(ttl_seconds=60)
        await dedup.register("msg-001")
        assert await dedup.is_duplicate("msg-002") is False

    async def test_expired_entry_not_duplicate(self):
        dedup = MessageDeduplicator(ttl_seconds=0.05)
        await dedup.register("msg-001")
        await asyncio.sleep(0.1)
        assert await dedup.is_duplicate("msg-001") is False

    async def test_size_increases_on_register(self):
        dedup = MessageDeduplicator(ttl_seconds=60)
        assert dedup.size == 0
        await dedup.register("a")
        await dedup.register("b")
        assert dedup.size == 2

    async def test_register_same_id_twice_is_idempotent(self):
        dedup = MessageDeduplicator(ttl_seconds=60)
        await dedup.register("msg-001")
        await dedup.register("msg-001")
        assert dedup.size == 1
        assert await dedup.is_duplicate("msg-001") is True

    async def test_purge_removes_expired_entries(self):
        dedup = MessageDeduplicator(ttl_seconds=0.05)
        await dedup.register("old")
        assert dedup.size == 1

        await asyncio.sleep(0.1)
        await dedup.register("new")  # triggers purge of "old"

        assert dedup.size == 1  # "old" purged, "new" added

    async def test_concurrent_register_no_race(self):
        dedup = MessageDeduplicator(ttl_seconds=60)
        ids = [f"msg-{i}" for i in range(50)]
        await asyncio.gather(*[dedup.register(mid) for mid in ids])
        assert dedup.size == 50
        for mid in ids:
            assert await dedup.is_duplicate(mid) is True
