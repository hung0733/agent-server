from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from backend.i18n import t
logger = logging.getLogger(__name__)


class ManagedTimer:
    def __init__(self, name: str) -> None:
        self._name = name
        self._task: asyncio.Task | None = None
        self._destroyed = False
        self._fire_at_ms: int = 0
        self._callback: Callable | None = None

    def schedule(self, delay_seconds: float, callback: Callable) -> None:
        if self._destroyed:
            return
        self.cancel()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        self._fire_at_ms = int(now_ms + delay_seconds * 1000)
        self._callback = callback
        self._task = asyncio.create_task(self._run_timer(delay_seconds, callback))

    def schedule_at(self, epoch_ms: int, callback: Callable) -> None:
        if self._destroyed:
            return
        if self._task is not None and epoch_ms >= self._fire_at_ms:
            return
        self.cancel()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        delay = max(0, (epoch_ms - now_ms) / 1000.0)
        self._fire_at_ms = epoch_ms
        self._callback = callback
        self._task = asyncio.create_task(self._run_timer(delay, callback))

    def try_advance_to(self, epoch_ms: int, callback: Callable) -> None:
        if self._destroyed:
            return
        if self._task is None:
            return
        if epoch_ms >= self._fire_at_ms:
            return
        self.cancel()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        delay = max(0, (epoch_ms - now_ms) / 1000.0)
        self._fire_at_ms = epoch_ms
        self._callback = callback
        self._task = asyncio.create_task(self._run_timer(delay, callback))

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._fire_at_ms = 0
        self._callback = None

    def flush(self) -> None:
        if self._destroyed:
            return
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._fire_at_ms = 0
        self._callback = None

    @property
    def pending(self) -> bool:
        return self._task is not None

    @property
    def scheduled_time_ms(self) -> int:
        return self._fire_at_ms

    def destroy(self) -> None:
        self._destroyed = True
        self.cancel()

    async def _run_timer(self, delay_seconds: float, callback: Callable) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            if not self._destroyed:
                await callback()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(t("tdai_memory.utils.managed_timer_callback_failed"), self._name)
