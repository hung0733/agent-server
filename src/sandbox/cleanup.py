from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sandbox.models import SandboxHandle
from sandbox.registry import SandboxRegistry


logger = logging.getLogger(__name__)


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
            try:
                last_used = datetime.fromisoformat(last_used_at)
            except ValueError:
                logger.warning("sandbox.janitor.invalid_timestamp sandbox_id=%s value=%s", handle.sandbox_id, last_used_at)
                continue
            if last_used <= cutoff:
                expired.append(handle)
        return expired

    async def destroy_expired_idle_handles(self, provider) -> list[str]:
        destroyed: list[str] = []
        for handle in self.expired_idle_handles(provider.registry):
            try:
                await provider.destroy(handle)
            except Exception as exc:
                logger.warning("sandbox.janitor.destroy_failed sandbox_id=%s error=%s", handle.sandbox_id, exc)
                continue
            destroyed.append(handle.sandbox_id)
            logger.info("sandbox.janitor.destroy sandbox_id=%s", handle.sandbox_id)
        return destroyed


async def run_sandbox_janitor_once(provider, idle_timeout_seconds: int) -> list[str]:
    janitor = SandboxJanitor(idle_timeout_seconds=idle_timeout_seconds)
    return await janitor.destroy_expired_idle_handles(provider)


async def run_sandbox_janitor_forever(provider, idle_timeout_seconds: int, interval_seconds: int | None = None) -> None:
    interval = interval_seconds or max(1, idle_timeout_seconds)
    while True:
        try:
            await run_sandbox_janitor_once(provider, idle_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("sandbox.janitor.loop_failed error=%s", exc)
        await asyncio.sleep(interval)
