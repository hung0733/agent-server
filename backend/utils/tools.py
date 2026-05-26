from __future__ import annotations

import asyncio
import logging
from typing import Set

import os
from backend.i18n import t

logger = logging.getLogger(__name__)


class Tools:
    _pending_tasks: Set[asyncio.Task] = set()

    @classmethod
    async def wait_task_comp(cls) -> None:
        """
        等待所有_pending_tasks 完成

        用於關閉前確保所有異步任務完成
        """
        if cls._pending_tasks:
            logger.info(t("utils.tools.waiting_pending_tasks"), len(cls._pending_tasks))
            await asyncio.gather(*cls._pending_tasks, return_exceptions=True)
            cls._pending_tasks.clear()

    @staticmethod
    def start_async_task(coro):
        """
        啟動資料庫異步任務並加入_pending_tasks 集合

        Args:
            coro: 要執行的 coroutine

        Returns:
            asyncio.Task: 創建的任務對象
        """
        task = asyncio.create_task(coro)
        Tools._pending_tasks.add(task)
        task.add_done_callback(Tools._pending_tasks.discard)
        return task

    @staticmethod
    def require_env(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(t("llm.missing_config") % name)
        return value
