from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from backend.i18n import t
from ..config import MemoryConfig
from ..store.postgres import PostgresStore

logger = logging.getLogger(__name__)


class MemoryCleaner:
    def __init__(self, postgres: PostgresStore, config: MemoryConfig, data_dir: str) -> None:
        self._postgres = postgres
        self._config = config
        self._data_dir = data_dir
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._clean_loop())
        logger.info(t("tdai_memory.pipeline.memory_cleaner_started"))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(t("tdai_memory.pipeline.memory_cleaner_stopped"))

    async def _clean_loop(self) -> None:
        while True:
            try:
                now = datetime.now()
                next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                sleep_seconds = (next_run - now).total_seconds()
                await asyncio.sleep(sleep_seconds)

                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(t("tdai_memory.pipeline.memory_cleaner_loop_error"))
                await asyncio.sleep(3600)

    async def run_once(self) -> None:
        retention_days = self._config.capture.l0_l1_retention_days
        if retention_days <= 0:
            logger.debug(t("tdai_memory.pipeline.memory_cleaner_retention_disabled"))
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_iso = cutoff.isoformat()

        l0_deleted = await self._postgres.delete_l0_expired(cutoff_iso)
        l1_deleted = await self._postgres.delete_l1_expired(cutoff_iso)

        logger.info(
            t("tdai_memory.pipeline.memory_cleaner_run_once_deleted"),
            l0_deleted, l1_deleted, cutoff_iso,
        )
