import asyncio
import logging
import os
from typing import Any, Set

import tiktoken

from i18n import _

logger = logging.getLogger(__name__)


class Tools:
    _pending_tasks: Set[asyncio.Task] = set()

    @staticmethod
    def require_env(name: str) -> str:
        value = os.getenv(name)
        if value is None:
            raise RuntimeError(_("Required environment variable '%s' is not set"), name)
        return value

    @classmethod
    async def wait_task_comp(cls) -> None:
        """
        等待所有_pending_tasks 完成

        用於關閉前確保所有異步任務完成
        """
        if cls._pending_tasks:
            logger.info(f"⏳ 正在等待 {len(cls._pending_tasks)} 個儲存任務完成...")
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
    def get_token_count(text: Any) -> int:
        """計吓段文字有幾多 Token"""
        try:
            return len(tiktoken.get_encoding("cl100k_base").encode(str(text)))
        except Exception:
            return len(str(text))
