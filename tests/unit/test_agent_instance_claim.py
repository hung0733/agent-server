from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.dao.agent_instance_dao import _stale_busy_cutoff


def test_stale_busy_cutoff_marks_old_heartbeat_as_reclaimable() -> None:
    now = datetime(2026, 3, 30, 10, 20, tzinfo=UTC)
    heartbeat = now - timedelta(minutes=10)

    assert _stale_busy_cutoff(now=now) > heartbeat


def test_stale_busy_cutoff_keeps_recent_heartbeat_non_reclaimable() -> None:
    now = datetime(2026, 3, 30, 10, 20, tzinfo=UTC)
    heartbeat = now - timedelta(seconds=30)

    assert _stale_busy_cutoff(now=now) < heartbeat
