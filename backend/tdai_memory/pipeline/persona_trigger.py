from __future__ import annotations

import asyncio
import logging
import os
import re

from ..utils.sanitize import escape_xml_tags

logger = logging.getLogger(__name__)

_SCENE_NAV_RE = re.compile(r"## 📑 场景导航[\s\S]*$")


class PersonaTrigger:
    def __init__(self, interval: int, data_dir: str):
        self.interval = interval
        self.data_dir = data_dir

    async def should_generate(
        self,
        *,
        agent_id: str,
        request_persona_update: bool = False,
        persona_update_reason: str = "",
        total_processed: int = 0,
        last_persona_at: float = 0,
        memories_since_last_persona: int = 0,
        scenes_processed: int = 0,
    ) -> tuple[bool, str]:
        if request_persona_update:
            return True, f"主动请求: {persona_update_reason}"

        if total_processed > 0 and last_persona_at == 0 and scenes_processed > 0:
            return True, "冷启动"

        if last_persona_at > 0 and not await self._has_persona_body(agent_id):
            return True, "恢复：persona.md 为空"

        if scenes_processed == 1 and memories_since_last_persona > 0:
            return True, "首个场景块"

        if memories_since_last_persona >= self.interval:
            return True, "达到阈值"

        return False, ""

    async def _has_persona_body(self, agent_id: str) -> bool:
        path = os.path.join(self.data_dir, agent_id, "persona.md")

        def _read_and_strip() -> str | None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                return None
            return _SCENE_NAV_RE.sub("", content).strip()

        content = await asyncio.to_thread(_read_and_strip)
        if content is None:
            return False
        return bool(content)
