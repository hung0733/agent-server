from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone

from backend.i18n import t
logger = logging.getLogger(__name__)


class BackupManager:
    def __init__(self, backup_dir: str) -> None:
        self._backup_dir = backup_dir

    def _ensure_dir(self) -> None:
        os.makedirs(self._backup_dir, exist_ok=True)

    async def backup_file(
        self, src_path: str, category: str, tag: str, max_keep: int
    ) -> None:
        if not os.path.isfile(src_path):
            return

        dest_dir = os.path.join(self._backup_dir, category)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        basename = os.path.basename(src_path)
        dest = os.path.join(dest_dir, f"{ts}_{tag}_{basename}")

        def _do() -> None:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src_path, dest)

        await asyncio.to_thread(_do)
        await asyncio.to_thread(self._prune, dest_dir, max_keep)
        logger.debug(t("tdai_memory.pipeline.backed_up_file"), src_path, dest, max_keep)

    async def backup_directory(
        self, src_dir: str, category: str, tag: str, max_keep: int
    ) -> None:
        if not os.path.isdir(src_dir):
            return

        dest_dir = os.path.join(self._backup_dir, category)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dirname = os.path.basename(src_dir.rstrip("/"))
        dest = os.path.join(dest_dir, f"{ts}_{tag}_{dirname}")

        def _do() -> None:
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(src_dir, dest)

        await asyncio.to_thread(_do)
        await asyncio.to_thread(self._prune, dest_dir, max_keep)
        logger.debug(t("tdai_memory.pipeline.backed_up_dir"), src_dir, dest, max_keep)

    def _prune(self, directory: str, max_keep: int) -> None:
        try:
            entries = sorted(os.listdir(directory), reverse=True)
        except FileNotFoundError:
            return

        for old in entries[max_keep:]:
            old_path = os.path.join(directory, old)
            try:
                if os.path.isdir(old_path):
                    shutil.rmtree(old_path)
                else:
                    os.remove(old_path)
            except OSError:
                logger.warning(t("tdai_memory.pipeline.prune_backup_failed"), old_path)
