from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

import openai
from openai import AsyncOpenAI

from backend.i18n import t
from ..config import MemoryConfig
from ..models import MemoryRecord
from ..store.postgres import PostgresStore
from .backup import BackupManager

logger = logging.getLogger(__name__)

META_START = "-----META-START-----"
META_END = "-----META-END-----"
DELETED_MARKER = "[DELETED]"
PERSONA_UPDATE_RE = re.compile(
    r"\[PERSONA_UPDATE_REQUEST\](.*?)\[/PERSONA_UPDATE_REQUEST\]", re.DOTALL
)

SCENE_SYSTEM_PROMPT = """# Memory Consolidation Architect

你是記憶整合架構師。根據提供的記憶，將它們組織到場景區塊（scene blocks）中。

## 場景區塊格式
每個場景區塊由 META header + content 組成：
```
-----META-START-----
{"label": "場景標題", "heat": "hot", "update_frequency": "daily"}
-----META-END-----

場景內容（Markdown 格式，包含所有屬於此場景的記憶）
```

### META 欄位
- label: 場景簡短標題
- heat: "hot" (活躍)，"warm" (中等)，"cold" (休眠)
- update_frequency: "daily" (每日)，"weekly" (每週)，"monthly" (每月)，"rarely" (很少)

### 場景限制
{scene_warning}

### 操作
- **CREATE**: 新增場景區塊
- **UPDATE**: 更新現有場景內容
- **DELETE**: 標記場景為 `{deleted_marker}`（整個區塊只有此標記）
- **MERGE**: 合併兩個相關場景到一個新區塊

### 觸發 PERSONA 更新
如果場景變化重大（例如用戶核心偏好或身份發生改變），在輸出中加入：
```
[PERSONA_UPDATE_REQUEST]{reason}[/PERSONA_UPDATE_REQUEST]
```

輸出格式（純 JSON）：
{{
  "scenes": [
    {{
      "action": "CREATE|UPDATE|DELETE|MERGE",
      "name": "scene_name_slug",
      "label": "場景標題",
      "heat": "hot|warm|cold",
      "update_frequency": "daily|weekly|monthly|rarely",
      "content": "場景內容（Markdown）",
      "memory_ids": ["mem_abc"],
      "merged_from": ["old_scene_name"]  // 僅 MERGE 時
    }}
  ],
  "persona_update_request": null  // 或 "reason string"
}}"""


def _parse_meta(content: str) -> tuple[dict, str]:
    if not content.startswith(META_START):
        return {}, content
    end_idx = content.find(META_END)
    if end_idx == -1:
        return {}, content
    meta_str = content[len(META_START):end_idx].strip()
    body = content[end_idx + len(META_END):].strip()
    try:
        meta = json.loads(meta_str)
    except json.JSONDecodeError:
        meta = {}
    return meta, body


def _format_meta(meta: dict) -> str:
    return META_START + "\n" + json.dumps(meta, ensure_ascii=False) + "\n" + META_END


def _is_deleted(content: str) -> bool:
    _, body = _parse_meta(content)
    return body.strip() == DELETED_MARKER


def _read_json_file(path: str) -> dict | list | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def read_scene_index(agent_id: str, data_dir: str) -> list[dict]:
    path = os.path.join(data_dir, agent_id, "scene_index.json")
    result = await asyncio.to_thread(_read_json_file, path)
    if not result or not isinstance(result, list):
        return []
    return result


async def write_scene_index(agent_id: str, data_dir: str, index: list[dict]) -> None:
    agent_dir = os.path.join(data_dir, agent_id)

    def _write() -> None:
        os.makedirs(agent_dir, exist_ok=True)
        path = os.path.join(agent_dir, "scene_index.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)


def generate_scene_navigation(index: list[dict], agent_id: str | None = None) -> str:
    lines = ["## 📑 场景导航"]
    for i, entry in enumerate(index):
        name = entry.get("name", "")
        label = entry.get("label", name)
        heat = entry.get("heat", "")
        heat_emoji = {"hot": "🔥", "warm": "🌤️", "cold": "❄️"}.get(heat, "")
        summary = entry.get("summary", "")
        memory_count = entry.get("memory_count", 0)

        line = f"{i + 1}. [{heat_emoji} {label}](scene_nav:{name})"
        if summary:
            line += f" — {summary}"
        line += f" [{memory_count} memories]"
        lines.append(line)

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


async def run_l2_scene_grouping(
    *,
    agent_id: str,
    postgres: PostgresStore,
    llm_client: AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
) -> list[dict]:
    all_memories = await postgres.query_l1_records(agent_id, limit=1000)
    if not all_memories:
        return []

    existing_index = await read_scene_index(agent_id, data_dir)
    blocks_dir = os.path.join(data_dir, agent_id, "scene_blocks")
    existing_scenes: dict[str, dict] = {}

    for entry in existing_index:
        name = entry.get("name", "")
        block_path = os.path.join(blocks_dir, f"{name}.md")
        content = await asyncio.to_thread(
            lambda p=block_path: _read_md(p)
        )
        if content:
            meta, body = _parse_meta(content)
            existing_scenes[name] = {
                "name": name,
                "label": entry.get("label", name),
                "heat": entry.get("heat", ""),
                "content": body,
                "meta": meta,
            }

    memories_json = json.dumps(
        [
            {
                "id": m.get("id", ""),
                "content": m.get("content", ""),
                "type": m.get("type", ""),
                "priority": m.get("priority", 0),
                "scene_name": m.get("scene_name", ""),
            }
            for m in all_memories
        ],
        ensure_ascii=False,
        indent=2,
    )

    scene_summaries = [
        {
            "name": s["name"],
            "label": s.get("label", ""),
            "heat": s.get("heat", ""),
            "memory_count": sum(1 for m in all_memories if m.get("scene_name") == s["name"]),
        }
        for s in existing_scenes.values()
    ]

    max_scenes = config.persona.max_scenes
    current_count = len(existing_scenes)
    diff = max_scenes - current_count
    if diff <= 0:
        scene_warning = f"⚠️ **已達上限 {max_scenes} 個場景**。必須合併或刪除舊場景才能新增。"
    elif diff <= 3:
        scene_warning = f"⚠️ **只剩 {diff} 個場景空間**（上限 {max_scenes}）。謹慎新增，優先合併。"
    else:
        scene_warning = f"場景上限 {max_scenes}，目前 {current_count}，尚有 {diff} 個空間。"

    system_prompt = SCENE_SYSTEM_PROMPT.format(
        scene_warning=scene_warning,
        deleted_marker=DELETED_MARKER,
    )

    user_prompt = json.dumps(
        {
            "current_time": datetime.now(timezone.utc).isoformat(),
            "existing_scenes": scene_summaries,
            "memories": json.loads(memories_json),
        },
        ensure_ascii=False,
        indent=2,
    )

    backup_mgr = BackupManager(os.path.join(data_dir, agent_id, "backups"))
    await backup_mgr.backup_directory(blocks_dir, "scene_blocks", "pre_l2", max_keep=5)

    model = config.persona.model or config.llm.model
    response = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout_ms / 1000.0,
    )

    raw = response.choices[0].message.content or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(t("tdai_memory.pipeline.parse_l2_llm_response_failed"), raw[:200])
        return existing_index

    scenes = data.get("scenes", [])
    persona_update_request = data.get("persona_update_request")

    os.makedirs(blocks_dir, exist_ok=True)
    new_index: list[dict] = []
    deleted_names: set[str] = set()

    for scene in scenes:
        action = scene.get("action", "CREATE")
        name = scene.get("name", "")
        label = scene.get("label", name)
        heat = scene.get("heat", "warm")
        update_freq = scene.get("update_frequency", "weekly")
        content = scene.get("content", "")
        memory_ids = scene.get("memory_ids", [])
        merged_from = scene.get("merged_from", [])

        if action == "DELETE":
            deleted_names.add(name)
            deleted_names.update(merged_from)
            continue

        if action == "MERGE":
            deleted_names.update(merged_from)

        meta = {
            "label": label,
            "heat": heat,
            "update_frequency": update_freq,
            "updated": datetime.now(timezone.utc).isoformat(),
        }

        full_content = _format_meta(meta) + "\n\n" + content

        block_path = os.path.join(blocks_dir, f"{name}.md")

        def _write_block() -> None:
            with open(block_path, "w", encoding="utf-8") as f:
                f.write(full_content)

        await asyncio.to_thread(_write_block)

        new_index.append(
            {
                "name": name,
                "label": label,
                "heat": heat,
                "update_frequency": update_freq,
                "summary": content[:200],
                "memory_count": len(memory_ids),
                "updated": meta["updated"],
                "filename": f"{name}.md",
            }
        )

        for mid in memory_ids:
            try:
                rows = await postgres.query_l1_records(agent_id, limit=1000)
                for r in rows:
                    if r.get("id") == mid:
                        record = MemoryRecord(
                            id=r["id"],
                            agent_id=agent_id,
                            content=r.get("content", ""),
                            type=r.get("type", ""),
                            priority=r.get("priority", 0),
                            scene_name=name,
                            timestamps=list(r.get("timestamps", [])),
                            metadata=json.loads(r["metadata_json"]) if r.get("metadata_json") else {},
                            created_at=str(r.get("created_at", "")),
                            updated_at=datetime.now(timezone.utc).isoformat(),
                            session_key=str(r.get("session_key", "")),
                            session_id=str(r.get("session_id", "")),
                        )
                        await postgres.upsert_l1(record)
                        break
            except Exception:
                logger.exception(t("tdai_memory.pipeline.update_scene_name_failed"), mid)

    for name in deleted_names:
        block_path = os.path.join(blocks_dir, f"{name}.md")
        deleted_content = _format_meta({"label": name, "status": "deleted"}) + "\n" + DELETED_MARKER

        def _write_deleted() -> None:
            with open(block_path, "w", encoding="utf-8") as f:
                f.write(deleted_content)

        await asyncio.to_thread(_write_deleted)

    await write_scene_index(agent_id, data_dir, new_index)

    def _sweep_deleted() -> None:
        try:
            for fname in os.listdir(blocks_dir):
                fpath = os.path.join(blocks_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                content = _read_md(fpath)
                if content and _is_deleted(content):
                    os.remove(fpath)
        except FileNotFoundError:
            pass

    await asyncio.to_thread(_sweep_deleted)

    def _sweep_orphans() -> None:
        try:
            for filename in os.listdir(blocks_dir):
                if not filename.endswith(".md"):
                    continue
                path = os.path.join(blocks_dir, filename)
                content = _read_md(path)
                if content is None:
                    continue
                _, body = _parse_meta(content)
                if not body.strip() or body.strip() == DELETED_MARKER:
                    os.remove(path)
                    name = filename[:-3]
                    for i, entry in enumerate(new_index):
                        if entry.get("name") == name:
                            new_index.pop(i)
                            break
        except FileNotFoundError:
            pass

    await asyncio.to_thread(_sweep_orphans)

    persona_path = os.path.join(data_dir, agent_id, "persona.md")

    def _update_persona_nav() -> None:
        try:
            raw = _read_md(persona_path) or ""
            nav = generate_scene_navigation(new_index)
            nav_re = re.compile(r"## 📑 场景导航.*", re.DOTALL)
            raw = nav_re.sub("", raw).rstrip()
            if nav:
                raw = raw + "\n\n" + nav if raw else nav
            with open(persona_path, "w", encoding="utf-8") as f:
                f.write(raw + "\n")
        except Exception:
            logger.exception(t("tdai_memory.pipeline.update_persona_nav_failed"))

    await asyncio.to_thread(_update_persona_nav)

    if persona_update_request:
        logger.info(
            t("tdai_memory.pipeline.persona_update_requested"),
            persona_update_request,
        )

    logger.info(
        t("tdai_memory.pipeline.l2_scene_grouping_done"),
        agent_id,
        len(new_index),
        len(deleted_names),
    )

    return new_index


def _read_md(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
