from __future__ import annotations

import asyncio
import glob as _glob
import json
import logging
import os
from datetime import datetime, timezone

import openai

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.models import MemoryRecord
from backend.tdai_memory.store.postgres import PostgresStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个记忆场景分组助手。根据给定的L1记忆列表和已有的场景信息，将所有记忆分配到合适的场景中。

规则：
1. 每个记忆必须恰好属于一个场景。
2. 语义相关的记忆应归入同一场景。
3. 如果记忆与某个已有场景匹配，归入该场景并设置 is_new 为 false。
4. 如果有记忆不属于任何已有场景，创建新场景并设置 is_new 为 true。
5. 场景名称 (name) 使用英文 slug 格式，如 "daily_chat"、"project_work"。
6. 场景标题 (title) 使用中文，简洁描述场景。
7. memory_ids 中只包含实际存在的记忆 ID。

请返回严格的 JSON 格式结果。"""


async def run_l2_scene_grouping(
    *,
    agent_id: str,
    postgres: PostgresStore,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
) -> list[dict]:
    memories = await postgres.query_l1_records(agent_id, limit=1000)

    scene_dir = os.path.join(data_dir, agent_id, "scene_blocks")
    os.makedirs(scene_dir, exist_ok=True)

    index_path = os.path.join(data_dir, agent_id, "scene_index.json")

    existing_index = await read_scene_index(agent_id, data_dir)

    scene_files = await asyncio.to_thread(_glob.glob, os.path.join(scene_dir, "*.md"))
    existing_scenes: dict[str, str] = {}
    for sf in scene_files:
        content = await asyncio.to_thread(_read_file, sf)
        existing_scenes[os.path.basename(sf)] = content

    memory_list: list[dict] = []
    for m in memories:
        memory_list.append({
            "id": m["id"],
            "content": m["content"],
            "type": m["type"],
            "priority": m["priority"],
            "current_scene": m.get("scene_name", "") or "",
        })

    user_prompt = _build_user_prompt(memory_list, existing_index, existing_scenes)

    response = await llm_client.chat.completions.create(
        model=config.llm.model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=config.llm.max_tokens,
    )

    result = json.loads(
        response.choices[0].message.content
        if response.choices
        else "{}"
    )
    scenes: list[dict] = result.get("scenes", [])

    memory_map: dict[str, dict] = {m["id"]: m for m in memories}

    new_index: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for scene in scenes:
        scene_name: str = scene["name"]
        title: str = scene["title"]
        description: str = scene["description"]
        memory_ids: list[str] = scene.get("memory_ids", [])

        md_lines = [f"# {title}", "", f"{description}", ""]
        for mid in memory_ids:
            mem = memory_map.get(mid)
            if mem is None:
                continue
            md_lines.append(f"## {mid}")
            md_lines.append(f"**类型**: {mem['type']}")
            md_lines.append(f"**优先级**: {mem['priority']}")
            md_lines.append("")
            md_lines.append(mem["content"])
            md_lines.append("")

        md_content = "\n".join(md_lines)
        md_filename = f"{scene_name}.md"
        md_path = os.path.join(scene_dir, md_filename)

        await asyncio.to_thread(_write_file, md_path, md_content)

        memory_count = len(memory_ids)
        new_index.append({
            "filename": md_filename,
            "title": title,
            "description": description,
            "updated": now_iso,
            "memory_count": memory_count,
        })

        for mid in memory_ids:
            mem = memory_map.get(mid)
            if mem is None:
                continue
            if mem.get("scene_name", "") != scene_name:
                record = MemoryRecord(
                    id=mem["id"],
                    agent_id=mem["agent_id"],
                    content=mem["content"],
                    type=mem["type"],
                    priority=mem["priority"],
                    scene_name=scene_name,
                    timestamps=list(mem.get("timestamps") or []),
                    created_at=str(mem.get("created_at") or now_iso),
                    updated_at=now_iso,
                    session_key=str(mem.get("session_key") or ""),
                    session_id=str(mem.get("session_id") or ""),
                )
                await postgres.upsert_l1(record)

    index_json = json.dumps(new_index, ensure_ascii=False, indent=2)
    await asyncio.to_thread(_write_file, index_path, index_json)

    logger.info(
        "L2 scene grouping complete: agent=%s scenes=%d memories=%d",
        agent_id,
        len(new_index),
        len(memories),
    )

    return new_index


async def read_scene_index(agent_id: str, data_dir: str) -> list[dict]:
    index_path = os.path.join(data_dir, agent_id, "scene_index.json")
    try:
        content = await asyncio.to_thread(_read_file, index_path)
        return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def generate_scene_navigation(index: list[dict], agent_id: str | None = None) -> str:
    n = len(index)
    lines = [
        "## 📑 场景导航",
        "",
        f"当前共 {n} 个场景：",
        "",
    ]

    for i, scene in enumerate(index, 1):
        title = scene.get("title", "未命名场景")
        description = scene.get("description", "")
        filename = scene.get("filename", "")
        lines.append(f"{i}. [🔍 {title}](scene_nav:{filename}) — {description}")

    return "\n".join(lines)


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _build_user_prompt(
    memory_list: list[dict],
    existing_index: list[dict],
    existing_scenes: dict[str, str],
) -> str:
    parts: list[str] = []

    parts.append("## L1 记忆列表\n")
    if memory_list:
        parts.append("```json")
        parts.append(json.dumps(memory_list, ensure_ascii=False, indent=2))
        parts.append("```\n")
    else:
        parts.append("（无记忆）\n")

    parts.append("## 已有场景信息\n")
    if existing_index:
        parts.append("```json")
        parts.append(json.dumps(existing_index, ensure_ascii=False, indent=2))
        parts.append("```\n")
    else:
        parts.append("（无已有场景）\n")

    if existing_scenes:
        parts.append("## 已有场景内容\n")
        for filename, content in existing_scenes.items():
            parts.append(f"### {filename}\n")
            parts.append(content)
            parts.append("")

    parts.append("## 要求\n")
    parts.append("请根据以上信息，将所有 L1 记忆分配到场景中，返回 JSON 格式结果。")

    return "\n".join(parts)
