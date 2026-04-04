from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sandbox.models import SandboxHandle
from sandbox.registry import SandboxRegistry


class SandboxJanitor:
    def __init__(self, idle_timeout_seconds: int) -> None:
        self.idle_timeout_seconds = idle_timeout_seconds

    def expired_idle_handles(self, registry: SandboxRegistry) -> list[SandboxHandle]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.idle_timeout_seconds)
        expired = []
        for handle in registry.idle.values():
            last_used_at = handle.metadata.get("last_used_at")
            if not last_used_at:
                continue
            if datetime.fromisoformat(last_used_at) <= cutoff:
                expired.append(handle)
        return expired
