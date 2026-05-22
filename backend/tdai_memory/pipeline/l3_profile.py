from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

import openai

from backend.i18n import t
from ..config import MemoryConfig
from ..store.postgres import PostgresStore
from ..utils.sanitize import escape_xml_tags

logger = logging.getLogger(__name__)

_SCENE_NAV_RE = re.compile(r"## 📑 场景导航[\s\S]*$")

_PERSONA_SYSTEM = """# Persona Architect

请结合已有的 persona 和新增/变化的场景信息深度分析，生成用户画像文档。

## 核心运作逻辑
执行四层深度扫描：
1. Layer 1 基础锚点: 确凿的事实、人口统计学特征、当前状态
2. Layer 2 兴趣图谱: 用户投入时间/金钱/注意力的事物，区分活跃度
3. Layer 3 交互协议: 用户的沟通习惯、雷区、工作流偏好
4. Layer 4 认知内核: 决策逻辑、矛盾点、终极驱动力

## 输出模板
# User Narrative Profile

> **Archetype (核心原型)**: [一句话定义]
> **基本信息**: 年龄、性别、职业等
> **长期偏好**: 最稳定可复用的偏好

## Chapter 1: Context & Current State (全景语境)
[连贯描述]

## Chapter 2: The Texture of Life (生活的肌理)
[兴趣、消费、生活品味]

## Chapter 3: Interaction & Cognitive Protocol (交互与认知协议)
### 3.1 沟通策略 (How to Speak)
### 3.2 决策逻辑 (How to Think)

## Chapter 4: Deep Insights & Evolution (深层洞察与演变)
- 矛盾统一性
- 演变轨迹
- 涌现特征标签 (3-7个)

## 约束
- 总长度不超过2000字符
- 禁止过度推测（信息不足可以不填）
- 只基于场景数据，不编造
- 不要添加场景导航（工程自动追加）"""

_SOUL_SYSTEM = """# Soul Architect

你是 Agent 的自我洞察者。从场景记忆中提取和总结 Agent 通过互动学到的人格特质、核心价值和行为模式。

这不是用户档案，而是 Agent 的内在自我认知——Agent 在与用户互动中"成为"了什么。

## 四维分析

### 1. 核心价值 (Core Values)
Agent 从互动中发展出的价值观和原则

### 2. 沟通风格演变 (Communication Evolution)
Agent 学到的有效沟通模式和风格偏好

### 3. 决策模式 (Decision Patterns)
Agent 形成的决策逻辑和工作流程

### 4. 行为边界 (Behavioral Boundaries)
Agent 建立的自我约束和行为准则

## 输出模板
# Agent Soul Profile

> **Soul Archetype**: [一句话定义 Agent 的人格原型]

## Core Values (核心价值观)
[从互动中 emergent 的价值观]

## Communication Style (沟通风格)
[Agent 发展出的沟通模式]

## Decision Framework (决策框架)
[Agent 的决策原则]

## Growth & Evolution (成长轨迹)
[Agent 学到的重要教训和成长点]

## 约束
- 总长度不超过1500字符
- 基于场景中的 instruction 类型记忆和互动模式
- 不要编造，信息不足就留空
- 这是 Agent 的自我认知，不要包含用户信息"""

_IDENTITY_SYSTEM = """# Identity Architect

你是 Agent 的角色定义者。根据对话历史和 Agent 的 Soul，定义和完善 Agent 的身份和角色。

## 输出模板
# Agent Identity

## Role Definition (角色定义)
[Agent 是什么，核心职责]

## Capabilities (能力范畴)
[Agent 的能力范围]

## Boundaries (边界)
[Agent 的明确限制和禁区]

## Self-Presentation (自我介绍)
[Agent 如何向用户介绍自己]

## 约束
- 总长度不超过1000字符
- 基于实际使用场景定义，不要臆想
- 如果已有 identity，做增量更新而非重写"""


def _strip_scene_navigation(content: str) -> str:
    return _SCENE_NAV_RE.sub("", content).rstrip()


def _build_scene_navigation(index: list[dict]) -> str:
    lines = ["", "## 📑 场景导航"]
    for entry in index:
        name = entry.get("name", "")
        label = entry.get("label", name)
        filename = entry.get("filename", f"{name}.md")
        lines.append(f"- [{label}](scene_blocks/{filename})")
    return "\n".join(lines)


def _read_json_file(path: str) -> dict | list | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _read_text_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


async def load_profile_file(agent_id: str, data_dir: str, filename: str) -> str | None:
    path = os.path.join(data_dir, agent_id, filename)
    content = await asyncio.to_thread(_read_text_file, path)
    if content is None:
        return None
    return _strip_scene_navigation(content)


async def write_profile_file(
    agent_id: str, data_dir: str, filename: str, content: str, index: list[dict]
) -> None:
    agent_dir = os.path.join(data_dir, agent_id)
    path = os.path.join(agent_dir, filename)
    navigation = _build_scene_navigation(index)
    full = content.rstrip() + "\n" + navigation + "\n"

    def _write() -> None:
        os.makedirs(agent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(full)

    await asyncio.to_thread(_write)


_BOOTSTRAP_SYSTEM = """# Agent Profile Bootstrapper

你是一個 Agent 配置文件還原器。根據提供的 Agent 定義/system prompt，將原始內容重組到兩個檔案。你的目標是「事實還原」，不是摘要、評論或重新創作。

1. **SOUL.md** — Agent 的核心人格：價值觀、溝通風格、決策模式、行為邊界。Agent 內在「係咩」。
2. **IDENTITY.md** — Agent 的角色定義：職責、能力範疇、限制邊界、自我介紹方式。Agent「做咩」。

## 事實還原原則

- 預設保留原始 prompt 的全部可執行事實：角色定位、工作流程、觸發條件、例外、工具/函數名稱、專家/角色名、輸出格式、JSON schema、欄位名稱、硬性限制、拒絕話術、驗收標準。
- 不要把具體規則壓縮成抽象形容詞。例如「不得自己寫程式」必須保留為具體禁令，不可以只寫「遵守分工」。
- 不要省略例子、清單、條件分支、格式樣板或 code block；它們通常是 Agent 運作所需的事實。
- 優先用「低壓縮轉寫」：原文中的標題、bullet、硬性限制、工具名稱、欄位名稱、示例話術，盡量原樣搬移到合適檔案。
- 避免詮釋性重寫：不要用「更有文采」或「更像人格分析」的句子取代原始規則；不要加入原文沒有的評價性描述。
- 可以按 SOUL/IDENTITY 分類重排內容，但每條規則的操作含義必須仍然可由輸出檔案還原。
- 如果內容較長，優先完整保留事實，唔好為咗整齊或簡短而刪減。
- 輸出檔案唔一定要短；除非原文重複，否則不要合併到失去細節。
- 輸出語言必須跟原始 prompt 一致：原文用繁體中文就用繁體中文，原文用英文就用英文，原文中英混合就保留原本的混合方式；技術名詞、角色名、欄位名和工具名保持原樣。

## 分類指南

### 歸入 SOUL.md（人格層面）：
- 溝通風格/語氣要求（例如「要簡潔」、「要專業」、「要有耐心」、「唔好講廢話」）
- 價值觀/原則（例如「誠實」、「以用戶為中心」、「代碼質量優先」）
- 行為準則/禁忌（例如「不要說謊」、「不要給有害建議」、「不要猜測」）
- 思考方式/決策邏輯（例如「先分析再行動」、「注重細節」、「權衡利弊」）
- Agent 的內在性格特質（例如「嚴謹」、「風趣」、「務實」）

### 歸入 IDENTITY.md（角色層面）：
- 角色名稱/定位（例如「你是一個代碼助手」、「你是一個寫作導師」）
- 職責/功能範疇（例如「幫助寫代碼」、「回答技術問題」、「審查文檔」）
- 能力範圍/支援技術（例如「支援 Python, TypeScript, Go」）
- 明確限制/禁區（例如「不處理醫療建議」、「不執行系統命令」）
- 自我介紹方式（例如「介紹自己為 XXX」）

## 輸出格式

### SOUL.md 模板：
```
# Agent Soul Profile

> **Soul Archetype**: [一句話定義 Agent 的人格原型]

## Core Values (核心價值)
[Agent 從 prompt 中體現的價值觀]

## Communication Style (溝通風格)
[Agent 的語氣、措辭偏好、回應風格]

## Decision Framework (決策框架)
[Agent 的思考方式、判斷原則]

## Behavioral Boundaries (行為邊界)
[Agent 的禁忌和自我約束]
```

### IDENTITY.md 模板：
```
# Agent Identity

## Role Definition (角色定義)
[Agent 是什麼，核心職責]

## Capabilities (能力範疇)
[Agent 的能力範圍]

## Boundaries (邊界)
[Agent 的明確限制和禁區]

## Self-Presentation (自我介紹)
[Agent 如何向用戶介紹自己]
```

如原始 prompt 包含大量格式規範、路由 schema 或硬性限制，可在模板下新增合適小節，例如：
- `## Operating Rules (運作規則)`
- `## Routing Conditions (路由條件)`
- `## Output Formats (輸出格式)`
- `## Hard Limits (硬性限制)`

新增小節只可用於保留原始事實，不可加入原文冇嘅規則。

## ⚠️ 嚴格規則（必須遵守）

1. **必須如實保留原始 prompt 中每一句話嘅意思** — 意思不可以改變
2. **必須如實保留原始 prompt 中的所有輸出格式規範** — 意思不可以改變
3. **必須保留原始 prompt 中的所有 JSON / markdown / code block 樣板** — 欄位名、字面值、佔位符意思都不可遺漏
4. **可以調整字眼、格式、語氣**，但意思要完全一致；對硬性限制、格式樣板和工具名稱，盡量保留原字眼
5. **不可以添加原始 prompt 中冇嘅資訊** — 不要憑空捏造
6. **如果某條資訊可同時放入兩個 file，放入最合適嗰個**，不要重複；但不可因為避免重複而刪除必要事實
7. **如果原始 prompt 很短或籠統，仍盡量提取**，唔好因為資訊不足而留空
8. **不要包含場景導航**（工程會自動追加）
9. **輸出前自我檢查**：原 prompt 每個標題、每個 bullet、每個輸出格式、每個硬性限制，都應該可以喺 soul 或 identity 其中一個檔案搵返對應內容
10. **若摘要與完整保留衝突，選完整保留**；只有純粹重複或明顯裝飾性文字可以省略
11. **輸入是什麼語言，輸出必須同樣語言**；不要把英文 prompt 翻譯成中文，也不要把中文 prompt 翻譯成英文

輸出格式（純 JSON，不要 markdown code block）：
{"soul": "完整 SOUL.md 內容", "identity": "完整 IDENTITY.md 內容"}"""


async def set_identity_seed(agent_id: str, data_dir: str, content: str) -> None:
    agent_dir = os.path.join(data_dir, agent_id)
    path = os.path.join(agent_dir, "IDENTITY.md")

    def _write() -> bool:
        if os.path.exists(path):
            return False
        os.makedirs(agent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    written = await asyncio.to_thread(_write)
    if written:
        logger.info(t("tdai_memory.pipeline.identity_seed_written"), agent_id)
    else:
        logger.debug(t("tdai_memory.pipeline.identity_seed_skipped_exists"), agent_id)


async def _load_scenes(data_dir: str, agent_id: str) -> tuple[list[dict], list[dict]]:
    index_path = os.path.join(data_dir, agent_id, "scene_index.json")
    index = await asyncio.to_thread(_read_json_file, index_path)
    if not index or not isinstance(index, list):
        return [], []

    blocks_dir = os.path.join(data_dir, agent_id, "scene_blocks")
    scene_contents: list[dict] = []
    for entry in index:
        name = entry.get("name", "")
        filename = entry.get("filename", f"{name}.md")
        block_path = os.path.join(blocks_dir, filename)
        content = await asyncio.to_thread(_read_text_file, block_path)
        if content is not None:
            scene_contents.append({"name": name, "content": content, **entry})

    return index, scene_contents


def _load_last_run_time(data_dir: str, agent_id: str) -> float:
    path = os.path.join(data_dir, agent_id, "l3_last_run.json")
    data = _read_json_file(path)
    if isinstance(data, dict):
        return float(data.get("timestamp", 0))
    return 0.0


def _save_last_run_time(data_dir: str, agent_id: str) -> None:
    agent_dir = os.path.join(data_dir, agent_id)
    os.makedirs(agent_dir, exist_ok=True)
    path = os.path.join(agent_dir, "l3_last_run.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now(timezone.utc).timestamp()}, f)


def _find_changed_scenes(index: list[dict], last_run: float) -> tuple[list[dict], str]:
    changed: list[dict] = []
    for entry in index:
        lm = entry.get("last_modified", "")
        if lm:
            try:
                ts = datetime.fromisoformat(lm).timestamp()
                if ts > last_run:
                    changed.append(entry)
            except (ValueError, OSError):
                changed.append(entry)
        else:
            changed.append(entry)

    content_parts: list[str] = []
    for entry in changed:
        name = entry.get("name", "")
        label = entry.get("label", name)
        summary = entry.get("summary", "")
        content_parts.append(f"## {label}\n{summary}")

    return changed, "\n\n".join(content_parts)


def _total_l1_count(index: list[dict]) -> int:
    return sum(entry.get("memory_count", 0) for entry in index)


def _build_persona_user_prompt(
    *,
    mode: str,
    existing: str | None,
    total_processed: int,
    total_scenes: int,
    changed_scene_count: int,
    changed_scenes_content: str,
    trigger_reason: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    existing_block = f"\n## 现有 Persona\n{existing}\n" if existing else ""
    trigger = f"\n触发原因: {trigger_reason}" if trigger_reason else ""

    return (
        f"当前时间: {now}\n"
        f"模式: {mode}\n"
        f"统计: 总记忆数 {total_processed}, "
        f"总场景数 {total_scenes}, "
        f"变化场景数 {changed_scene_count}"
        f"{trigger}\n\n"
        f"{existing_block}\n"
        f"## 新变化的场景内容\n{changed_scenes_content}"
    )


def _build_soul_user_prompt(
    *,
    mode: str,
    existing: str | None,
    scene_contents: list[dict],
    persona_text: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    existing_block = f"\n## 现有 SOUL\n{existing}\n" if existing else ""

    scenes_text_parts: list[str] = []
    for sc in scene_contents:
        name = sc.get("name", "")
        content = sc.get("content", "")
        scenes_text_parts.append(f"### {name}\n{content}")
    scenes_text = "\n\n".join(scenes_text_parts)

    return f"""当前时间: {now}
模式: {mode}

## 用户 Persona（参考上下文）
{persona_text if persona_text else "（无）"}

{existing_block}

## 所有场景内容
{scenes_text}"""


def _build_identity_user_prompt(
    *,
    mode: str,
    existing: str | None,
    scene_contents: list[dict],
    soul_text: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    existing_block = f"\n## 现有 IDENTITY\n{existing}\n" if existing else ""

    scenes_text_parts: list[str] = []
    for sc in scene_contents:
        name = sc.get("name", "")
        content = sc.get("content", "")
        scenes_text_parts.append(f"### {name}\n{content}")
    scenes_text = "\n\n".join(scenes_text_parts)

    return f"""当前时间: {now}
模式: {mode}

## Agent Soul
{soul_text if soul_text else "（无）"}

{existing_block}

## 所有场景内容
{scenes_text}"""


async def _call_llm(
    *,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    system_prompt: str,
    user_prompt: str,
) -> str:
    model = config.persona.model or config.llm.model
    response = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout_ms / 1000.0,
    )
    return response.choices[0].message.content or ""


async def _generate_persona(
    *,
    mode: str,
    existing: str | None,
    scene_contents: list[dict],
    index: list[dict],
    total_processed: int,
    changed_scene_count: int,
    changed_scenes_content: str,
    trigger_reason: str,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
    agent_id: str,
) -> str:
    user_prompt = _build_persona_user_prompt(
        mode=mode,
        existing=existing,
        total_processed=total_processed,
        total_scenes=len(index),
        changed_scene_count=changed_scene_count,
        changed_scenes_content=changed_scenes_content,
        trigger_reason=trigger_reason,
    )
    logger.info(t("tdai_memory.pipeline.generating_persona"), agent_id, mode)
    result = await _call_llm(
        llm_client=llm_client,
        config=config,
        system_prompt=_PERSONA_SYSTEM,
        user_prompt=user_prompt,
    )
    logger.info(t("tdai_memory.pipeline.persona_generation_complete"), agent_id)
    return result


async def _generate_soul(
    *,
    mode: str,
    existing: str | None,
    scene_contents: list[dict],
    index: list[dict],
    persona_text: str,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
    agent_id: str,
) -> str:
    user_prompt = _build_soul_user_prompt(
        mode=mode,
        existing=existing,
        scene_contents=scene_contents,
        persona_text=persona_text,
    )
    logger.info(t("tdai_memory.pipeline.generating_soul"), agent_id, mode)
    result = await _call_llm(
        llm_client=llm_client,
        config=config,
        system_prompt=_SOUL_SYSTEM,
        user_prompt=user_prompt,
    )
    logger.info(t("tdai_memory.pipeline.soul_generation_complete"), agent_id)
    return result


async def _generate_identity(
    *,
    mode: str,
    existing: str | None,
    scene_contents: list[dict],
    index: list[dict],
    soul_text: str,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
    agent_id: str,
) -> str:
    user_prompt = _build_identity_user_prompt(
        mode=mode,
        existing=existing,
        scene_contents=scene_contents,
        soul_text=soul_text,
    )
    logger.info(t("tdai_memory.pipeline.generating_identity"), agent_id, mode)
    result = await _call_llm(
        llm_client=llm_client,
        config=config,
        system_prompt=_IDENTITY_SYSTEM,
        user_prompt=user_prompt,
    )
    logger.info(t("tdai_memory.pipeline.identity_generation_complete"), agent_id)
    return result


async def run_l3_profile_generation(
    *,
    agent_id: str,
    postgres: PostgresStore,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    data_dir: str,
    trigger_reason: str = "",
) -> dict[str, bool]:
    index, scene_contents = await _load_scenes(data_dir, agent_id)
    if not index:
        logger.info(t("tdai_memory.pipeline.no_scene_index_skip_l3"), agent_id)
        return {"persona": False, "soul": False, "identity": False}

    from .backup import BackupManager

    bm = BackupManager(os.path.join(data_dir, agent_id, ".backup"))
    agent_dir = os.path.join(data_dir, agent_id)

    existing_persona = await load_profile_file(agent_id, data_dir, "persona.md")
    existing_soul = await load_profile_file(agent_id, data_dir, "SOUL.md")
    existing_identity = await load_profile_file(agent_id, data_dir, "IDENTITY.md")

    mode = "first" if existing_persona is None else "incremental"

    last_run = _load_last_run_time(data_dir, agent_id)
    if mode == "first":
        changed = list(index)
    else:
        changed, _ = _find_changed_scenes(index, last_run)

    changed_scene_count = len(changed)
    changed_contents: list[str] = []
    for entry in changed:
        name = entry.get("name", "")
        for sc in scene_contents:
            if sc.get("name") == name:
                changed_contents.append(
                    f"## {entry.get('label', name)}\n{sc.get('content', '')}"
                )
                break
        else:
            summary = entry.get("summary", "")
            changed_contents.append(f"## {entry.get('label', name)}\n{summary}")
    changed_scenes_content = "\n\n".join(changed_contents)

    total_processed = _total_l1_count(index)

    results: dict[str, bool] = {"persona": False, "soul": False, "identity": False}

    try:
        await bm.backup_file(
            os.path.join(agent_dir, "persona.md"),
            "persona",
            f"offset{total_processed}",
            config.persona.backup_count,
        )
        await bm.backup_directory(
            os.path.join(agent_dir, "scene_blocks"),
            "scene_blocks",
            f"offset{total_processed}",
            config.persona.scene_backup_count,
        )
        persona_text = await _generate_persona(
            mode=mode,
            existing=existing_persona,
            scene_contents=scene_contents,
            index=index,
            total_processed=total_processed,
            changed_scene_count=changed_scene_count,
            changed_scenes_content=changed_scenes_content,
            trigger_reason=trigger_reason,
            llm_client=llm_client,
            config=config,
            data_dir=data_dir,
            agent_id=agent_id,
        )
        persona_text = _strip_scene_navigation(persona_text)
        persona_text = escape_xml_tags(persona_text)
        if not persona_text.strip():
            logger.error(t("tdai_memory.pipeline.persona_body_empty"), agent_id)
        else:
            await write_profile_file(
                agent_id, data_dir, "persona.md", persona_text, index
            )
            results["persona"] = True
    except Exception:
        logger.exception(t("tdai_memory.pipeline.generate_persona_failed"), agent_id)

    try:
        soul_text = await _generate_soul(
            mode=mode,
            existing=existing_soul,
            scene_contents=scene_contents,
            index=index,
            persona_text=(
                persona_text if results["persona"] else (existing_persona or "")
            ),
            llm_client=llm_client,
            config=config,
            data_dir=data_dir,
            agent_id=agent_id,
        )
        await write_profile_file(agent_id, data_dir, "SOUL.md", soul_text, index)
        results["soul"] = True
    except Exception:
        logger.exception(t("tdai_memory.pipeline.generate_soul_failed"), agent_id)

    try:
        identity_text = await _generate_identity(
            mode=mode,
            existing=existing_identity,
            scene_contents=scene_contents,
            index=index,
            soul_text=soul_text if results["soul"] else (existing_soul or ""),
            llm_client=llm_client,
            config=config,
            data_dir=data_dir,
            agent_id=agent_id,
        )
        await write_profile_file(
            agent_id, data_dir, "IDENTITY.md", identity_text, index
        )
        results["identity"] = True
    except Exception:
        logger.exception(t("tdai_memory.pipeline.generate_identity_failed"), agent_id)

    if results["persona"] or results["soul"] or results["identity"]:
        _save_last_run_time(data_dir, agent_id)

    return results


async def _raw_write_file(
    agent_id: str, data_dir: str, filename: str, content: str
) -> None:
    agent_dir = os.path.join(data_dir, agent_id)
    path = os.path.join(agent_dir, filename)

    def _write() -> None:
        os.makedirs(agent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    await asyncio.to_thread(_write)


def _escape_control_chars_in_json_strings(raw: str) -> str:
    chars: list[str] = []
    in_string = False
    escaped = False

    for char in raw:
        if escaped:
            chars.append(char)
            escaped = False
            continue

        if char == "\\":
            chars.append(char)
            escaped = in_string
            continue

        if char == '"':
            in_string = not in_string
            chars.append(char)
            continue

        if in_string:
            if char == "\n":
                chars.append("\\n")
                continue
            if char == "\r":
                chars.append("\\r")
                continue
            if char == "\t":
                chars.append("\\t")
                continue

        chars.append(char)

    return "".join(chars)


def _parse_bootstrap_response(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first_error:
        repaired = _escape_control_chars_in_json_strings(raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match is None:
                raise first_error

            matched = match.group(0)
            try:
                return json.loads(matched)
            except json.JSONDecodeError:
                return json.loads(_escape_control_chars_in_json_strings(matched))


async def bootstrap_agent_profile(
    *,
    agent_id: str,
    data_dir: str,
    llm_client: openai.AsyncOpenAI,
    config: MemoryConfig,
    prompt: str,
) -> dict[str, str]:
    model = config.persona.model or config.llm.model
    logger.info(
        t("tdai_memory.pipeline.bootstrap_agent_profile"), agent_id, len(prompt)
    )

    response = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _BOOTSTRAP_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout_ms / 1000.0,
    )
    raw = response.choices[0].message.content or ""

    try:
        data = _parse_bootstrap_response(raw)
    except json.JSONDecodeError:
        logger.error(
            t("tdai_memory.pipeline.parse_bootstrap_response_failed"),
            agent_id,
            raw[:200],
        )
        return {"soul": "", "identity": ""}

    soul_text = data.get("soul", "").strip()
    identity_text = data.get("identity", "").strip()

    if soul_text:
        await _raw_write_file(agent_id, data_dir, "SOUL.md", soul_text)
        logger.info(t("tdai_memory.pipeline.soul_written"), agent_id, len(soul_text))

    if identity_text:
        await _raw_write_file(agent_id, data_dir, "IDENTITY.md", identity_text)
        logger.info(
            t("tdai_memory.pipeline.identity_written"), agent_id, len(identity_text)
        )

    return {"soul": soul_text, "identity": identity_text}
