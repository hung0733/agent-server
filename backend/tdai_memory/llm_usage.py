from __future__ import annotations

from typing import Any

from backend.tdai_memory.config import MemoryConfig


def save_tdai_llm_usage(config: MemoryConfig, response: Any) -> None:
    llm_endpoint_id = config.llm.llm_ep_id
    if llm_endpoint_id > 0:
        from backend.utils.message import MsgUtil
        from backend.utils.tools import Tools

        Tools.start_async_task(MsgUtil.save_llm_usage(llm_endpoint_id, response))
