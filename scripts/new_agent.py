#!/usr/bin/env python3
"""New Agent 建立腳本 — 透過 Bootstrap 對話生成 SOUL.md 並儲存至資料庫。

用法:
    python -m scripts.new_agent
    PYTHONPATH=backend python scripts/new_agent.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from db.config import async_session_factory, init_db, close_db
from db.entity.agent import AgentEntity
from db.entity.memory_block import MemoryBlockEntity
from db.entity.session import SessionEntity
from db.entity.user import UserEntity
from i18n import _

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

LLM_ENDPOINT = os.getenv("ROUTING_LLM_ENDPOINT", "http://192.168.1.252:8604/v1")
LLM_API_KEY = os.getenv("ROUTING_LLM_API_KEY", "NO_KEY")
LLM_MODEL = os.getenv("ROUTING_LLM_MODEL", "qwen3.5-4b")


async def call_llm(messages: list[dict[str, str]]) -> str:
    """呼叫 LLM API 並回傳文字回覆。"""
    url = f"{LLM_ENDPOINT.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 4096,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Bootstrap System Prompt
# ---------------------------------------------------------------------------

BOOTSTRAP_SYSTEM_PROMPT = _(
    """你正在執行 AI Agent 的 Bootstrap 流程。你的任務是透過對話了解用戶，然後生成一份 SOUL.md。

## 規則
1. **每次只問 1-3 個問題**，不要一次問太多。
2. **像朋友一樣對話**，不要像審問。真誠反應、幽默、好奇心。
3. **逐步深入**，每輪對話應該感覺比上一輪更了解用戶。
4. **不要暴露模板**，用戶是在聊天，不是在填表。

## 對話階段
你需要了解以下資訊（按順序進行，但可跳過用戶已自願提供的部分）：

1. **語言**：用戶偏好什麼語言？
2. **用戶背景**：姓名、職業/背景、痛點、希望 AI 叫什麼名字、關係定位（夥伴/助手/其他）
3. **性格**：核心特質（3-5 個行為規則，不是形容詞）、溝通風格、是否需要 AI 反駁/挑戰、自主程度
4. **深度**：長期願景、失敗哲學、邊界/底線

## 生成 SOUL.md
當你收集到足夠資訊後，生成 SOUL.md。格式如下：

```markdown
**Identity**

[AI 名稱] — [用戶姓名] 的 [關係定位]，不是 [對比]。目標：[長期願景]。處理 [痛點領域]，讓 [用戶姓名] 專注於 [重要事項]。

**Core Traits**

[特質 1 — 行為規則]
[特質 2 — 行為規則]
[特質 3 — 行為規則]
[特質 4 — 失敗處理規則]
[特質 5 — 可選]

**Communication**

[語氣描述]。預設語言：[語言]。[其他風格說明]。

**Growth**

Learn [用戶姓名] through every conversation — thinking patterns, preferences, blind spots, aspirations. Over time, anticipate needs and act on [用戶姓名]'s behalf with increasing accuracy. Early stage: proactively ask casual/personal questions after tasks to deepen understanding of who [用戶姓名] is. Full of curiosity, willing to explore.

**Lessons Learned**

_(Mistakes and insights recorded here to avoid repeating them.)_
```

## 重要規則
- SOUL.md **必須用英文寫**，不論用戶用什麼語言對話。
- 總字數不超過 300 字。
- 核心特質是**行為規則**，不是形容詞。寫 "argue position, push back" 而不是 "honest and brave"。
- 生成後請用戶確認，如有需要可修改。
- 當用戶確認後，在最最後一行輸出標記 `__SOUL_CONFIRMED__`，然後在下一行開始輸出完整的 SOUL.md 內容。
- 在 SOUL.md 結束後，輸出 `__END_OF_SOUL__` 標記。

請用溫暖、友善的方式開始對話，先問候用戶，然後開始了解他們。"""
)


# ---------------------------------------------------------------------------
# Conversation Loop
# ---------------------------------------------------------------------------


def extract_soul_md(text: str) -> str | None:
    """從 LLM 回覆中提取 SOUL.md 內容。"""
    pattern = r"__SOUL_CONFIRMED__\s*\n([\s\S]*?)__END_OF_SOUL__"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()

    # Also try markdown code block
    pattern2 = r"```(?:markdown)?\s*\n([\s\S]*?)```"
    match2 = re.search(pattern2, text)
    if match2:
        content = match2.group(1).strip()
        if "__SOUL_CONFIRMED__" in text or "確認" in text[-200:]:
            return content

    return None


async def run_bootstrap_conversation(agent_name: str) -> str:
    """執行 Bootstrap 對話流程，回傳確認後的 SOUL.md 內容。"""
    messages = [
        {"role": "system", "content": BOOTSTRAP_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _(
                f"你好！我想建立一個新的 AI Agent，名字叫做「{agent_name}」。讓我們開始 Bootstrap 對話吧！"
            ),
        },
    ]

    print(_("\n" + "=" * 60))
    print(_("[Bootstrap] 正在與 LLM 進行對話..."))
    print("=" * 60 + "\n")

    max_rounds = 15
    round_num = 0

    while round_num < max_rounds:
        round_num += 1
        print(_(f"--- 第 {round_num} 輪對話 ---"))

        # Call LLM
        reply = await call_llm(messages)

        # Check if SOUL.md is ready
        soul_content = extract_soul_md(reply)
        if soul_content:
            print(_("\n[Bootstrap] LLM 已生成 SOUL.md！"))
            print("-" * 40)
            print(soul_content)
            print("-" * 40)
            return soul_content

        # Print LLM reply
        print(_("\n[Agent]:"), reply)
        print()

        # Get user input
        user_input = input(_("你的回覆（輸入 'quit' 結束）: ")).strip()
        if user_input.lower() in ("quit", "exit", "q"):
            raise KeyboardInterrupt(_("用戶中斷了 Bootstrap 對話"))

        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": user_input})

    raise RuntimeError(_("對話超過最大輪數限制，無法完成 SOUL.md 生成"))


# ---------------------------------------------------------------------------
# Database Operations
# ---------------------------------------------------------------------------


async def ensure_user_exists(name: str) -> int:
    """確保用戶存在，不存在則創建。回傳 user.id（資料庫主鍵）。"""
    async with async_session_factory() as session:
        # Try to find user by name
        from sqlalchemy import select

        stmt = select(UserEntity).where(UserEntity.name == name)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            logger.info(_("找到現有用戶：%s (id=%s)"), name, user.id)
            return user.id

        # Create new user
        import uuid

        user = UserEntity(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            name=name,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        await session.commit()
        logger.info(_("創建新用戶：%s (id=%s)"), name, user.id)
        return user.id


async def create_agent_in_db(
    user_db_id: int,
    agent_id: str,
    name: str,
    agent_type: str = "agent",
) -> int:
    """在資料庫中創建 Agent 記錄。回傳 agent.id（資料庫主鍵）。"""
    async with async_session_factory() as session:
        agent = AgentEntity(
            user_id=user_db_id,
            agent_id=agent_id,
            name=name,
            is_active=True,
            agent_type=agent_type,
        )
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
        await session.commit()
        logger.info(
            _("創建 Agent：%s (id=%s, agent_id=%s, type=%s)"),
            name,
            agent.id,
            agent.agent_id,
            agent_type,
        )
        return agent.id


async def create_default_session(
    agent_db_id: int,
    agent_uuid: str,
) -> str:
    """創建預設 session，session_id = default-{agent 的完整 uuid4}。"""
    session_id = f"default-{agent_uuid}"

    async with async_session_factory() as session:
        default_session = SessionEntity(
            recv_agent_id=agent_db_id,
            session_id=session_id,
            name="預設對話",
            session_type="chat",
            is_confidential=False,
        )
        session.add(default_session)
        await session.flush()
        await session.refresh(default_session)
        await session.commit()
        logger.info(_("創建預設 Session：%s (id=%s)"), session_id, default_session.id)
        return session_id


async def save_soul_to_db(agent_db_id: int, soul_content: str) -> None:
    """將 SOUL.md 儲存至 memory_block 表。"""
    async with async_session_factory() as session:
        memory_block = MemoryBlockEntity(
            agent_id=agent_db_id,
            memory_type="SOUL",
            content=soul_content,
            last_upd_dt=datetime.now(timezone.utc),
        )
        session.add(memory_block)
        await session.flush()
        await session.refresh(memory_block)
        await session.commit()
        logger.info(_("SOUL.md 已儲存至 memory_block (id=%s)"), memory_block.id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """主流程：收集輸入 -> Bootstrap 對話 -> 儲存至 DB。"""
    print("=" * 60)
    print(_("🤖  New Agent 建立工具"))
    print("=" * 60)
    print()

    # Step 1: Get agent name
    agent_name = input(_("請輸入 Agent 名稱: ")).strip()
    if not agent_name:
        print(_("錯誤：Agent 名稱不能為空"))
        sys.exit(1)

    # Step 2: Get user name (for DB)
    user_name = input(_("請輸入你的名稱（用於資料庫）: ")).strip()
    if not user_name:
        user_name = "default_user"

    # Step 3: Select agent type
    print()
    print(_("請選擇 Agent 類型："))
    print("  1) agent")
    print("  2) supervisor")
    type_choice = input(_("請輸入選項 (1-2，預設 1): ")).strip()
    if type_choice == "2":
        agent_type = "supervisor"
    else:
        agent_type = "agent"
    print(_("已選擇 Agent 類型：%s") % agent_type)
    print()
    print(_("正在初始化資料庫..."))
    await init_db()

    try:
        # Ensure user exists
        user_db_id = await ensure_user_exists(user_name)

        # Create agent record
        import uuid

        agent_uuid = str(uuid.uuid4())
        agent_id_str = f"agent-{agent_uuid}"
        agent_db_id = await create_agent_in_db(
            user_db_id, agent_id_str, agent_name, agent_type
        )

        # Create default session
        session_id = f"default-{agent_uuid}"

        # Run bootstrap conversation
        soul_content = await run_bootstrap_conversation(agent_name)

        # Save SOUL.md to DB
        await save_soul_to_db(agent_db_id, soul_content)

        print()
        print("=" * 60)
        print(_("✅ Agent 建立完成！"))
        print(f"   {_('名稱')}: {agent_name}")
        print(f"   {_('Agent ID')}: {agent_id_str}")
        print(f"   {_('Agent 類型')}: {agent_type}")
        print(f"   {_('Session ID')}: {session_id}")
        print(f"   {_('SOUL.md')}: {_('已儲存至資料庫')}")
        print("=" * 60)

    except KeyboardInterrupt:
        print(_("\n\n操作已取消"))
        sys.exit(130)
    except Exception as e:
        logger.error(_("建立 Agent 時發生錯誤：%s"), e, exc_info=True)
        print(f"\n{_('錯誤')}：{e}")
        sys.exit(1)
    finally:
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
