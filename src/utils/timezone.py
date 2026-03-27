"""Timezone utilities for agent-server.

Provides server timezone configuration and conversion utilities.
All database timestamps are stored in UTC, but user-facing outputs
and date-based grouping use the server's configured timezone.

Environment Variables:
    TZ: Server timezone (default: Asia/Hong_Kong)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from i18n import _


def get_server_tz() -> ZoneInfo:
    """Get server timezone from TZ environment variable.

    Returns:
        ZoneInfo object for the server timezone.
        Defaults to Asia/Hong_Kong if TZ is not set.

    Raises:
        ZoneInfoNotFoundError: If the timezone name is invalid.
    """
    tz_name = os.getenv("TZ", "Asia/Hong_Kong")
    return ZoneInfo(tz_name)


def now_server() -> datetime:
    """Get current datetime in server timezone.

    Returns:
        Timezone-aware datetime object in server timezone.

    Example:
        >>> now = now_server()
        >>> # When TZ=Asia/Hong_Kong
        >>> now.tzinfo  # ZoneInfo(key='Asia/Hong_Kong')
        >>> now.isoformat()  # '2026-03-27T10:07:13+08:00'
    """
    return datetime.now(get_server_tz())


def to_server_tz(dt: datetime) -> datetime:
    """Convert datetime to server timezone.

    If the input datetime is naive (no timezone info), it is assumed
    to be in UTC and converted accordingly.

    Args:
        dt: Datetime object to convert (can be naive or aware).

    Returns:
        Timezone-aware datetime in server timezone.

    Example:
        >>> from datetime import datetime, timezone
        >>> utc_time = datetime(2026, 3, 27, 2, 7, 13, tzinfo=timezone.utc)
        >>> hkt_time = to_server_tz(utc_time)
        >>> hkt_time.isoformat()  # '2026-03-27T10:07:13+08:00'
    """
    if dt.tzinfo is None:
        # Assume naive datetime is in UTC
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(get_server_tz())
