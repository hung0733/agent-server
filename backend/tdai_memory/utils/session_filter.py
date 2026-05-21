from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_NON_INTERACTIVE_PATTERNS = [
    "cron",
    "heartbeat",
    "automation",
    "schedule",
    "trigger",
    "healthcheck",
    "health-check",
    "ping",
    "keepalive",
    "keep-alive",
]

_SKIP_PREFIXES = [
    "memory-scene-extract-",
    "subagent:",
    "temp:",
    "memory-",
]


class SessionFilter:
    def __init__(self, exclude_agents: list[str] | None = None) -> None:
        self._exclude_agents = exclude_agents or []

    def is_non_interactive(self, session_key: str) -> bool:
        lower = session_key.lower()
        for pattern in _NON_INTERACTIVE_PATTERNS:
            if pattern in lower:
                return True
        return False

    def should_skip(self, session_key: str) -> bool:
        for prefix in _SKIP_PREFIXES:
            if session_key.startswith(prefix):
                return True
        if self.is_non_interactive(session_key):
            return True
        for agent in self._exclude_agents:
            if session_key == agent or session_key.startswith(f"agent:{agent}"):
                return True
        return False
