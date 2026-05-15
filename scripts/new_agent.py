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
from pathlib import Path

from alembic import command
from alembic.config import Config
import httpx
from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.session import async_session_factory, engine
from backend.entities import Agent, AgentSession, LlmGroup, MemoryBlock, UserAcc
from backend.i18n import t

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

BOOTSTRAP_SYSTEM_PROMPT = t("scripts.new_agent.bootstrap_system_prompt")


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
            "content": t("scripts.new_agent.bootstrap_user_start") % agent_name,
        },
    ]

    print("\n" + "=" * 60)
    print(t("scripts.new_agent.bootstrap_start"))
    print("=" * 60 + "\n")

    max_rounds = 15
    round_num = 0

    while round_num < max_rounds:
        round_num += 1
        print(t("scripts.new_agent.round") % round_num)

        # Call LLM
        reply = await call_llm(messages)

        # Check if SOUL.md is ready
        soul_content = extract_soul_md(reply)
        if soul_content:
            print(t("scripts.new_agent.bootstrap_ready"))
            print("-" * 40)
            print(soul_content)
            print("-" * 40)
            return soul_content

        # Print LLM reply
        print("\n[Agent]:", reply)
        print()

        # Get user input
        user_input = input(t("scripts.new_agent.reply_prompt")).strip()
        if user_input.lower() in ("quit", "exit", "q"):
            raise KeyboardInterrupt(t("scripts.new_agent.bootstrap_cancelled"))

        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": user_input})

    raise RuntimeError(t("scripts.new_agent.max_rounds_exceeded"))


# ---------------------------------------------------------------------------
# Database Operations
# ---------------------------------------------------------------------------


async def ensure_user_exists(name: str) -> int:
    """確保用戶存在，不存在則創建。回傳 user.id（資料庫主鍵）。"""
    async with async_session_factory() as session:
        stmt = select(UserAcc).where(UserAcc.name == name)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            logger.info(t("scripts.new_agent.existing_user"), name, user.id)
            return user.id

        # Create new user
        import uuid

        user = UserAcc(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            name=name,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        await session.commit()
        logger.info(t("scripts.new_agent.user_created"), name, user.id)
        return user.id


async def ensure_llm_group_exists(user_db_id: int, name: str = "default") -> int:
    """確保用戶有 LLM group，回傳 llm_group.id。"""
    async with async_session_factory() as session:
        stmt = select(LlmGroup).where(
            LlmGroup.user_id == user_db_id,
            LlmGroup.name == name,
        )
        result = await session.execute(stmt)
        group = result.scalar_one_or_none()

        if group:
            logger.info(t("scripts.new_agent.existing_llm_group"), name, group.id)
            return group.id

        group = LlmGroup(user_id=user_db_id, name=name)
        session.add(group)
        await session.flush()
        await session.refresh(group)
        await session.commit()
        logger.info(t("scripts.new_agent.llm_group_created"), name, group.id)
        return group.id


async def create_agent_in_db(
    user_db_id: int,
    llm_group_id: int,
    agent_id: str,
    name: str,
    agent_type: str = "agent",
) -> int:
    """在資料庫中創建 Agent 記錄。回傳 agent.id（資料庫主鍵）。"""
    async with async_session_factory() as session:
        agent = Agent(
            user_id=user_db_id,
            agent_id=agent_id,
            name=name,
            is_active=True,
            llm_group_id=llm_group_id,
            agent_type=agent_type,
        )
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
        await session.commit()
        logger.info(
            t("scripts.new_agent.agent_created"),
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
        default_session = AgentSession(
            recv_agent_id=agent_db_id,
            session_id=session_id,
            name=t("scripts.new_agent.default_session_name"),
            session_type="chat",
            sender_agent_id=agent_db_id,
            is_confidential=False,
        )
        session.add(default_session)
        await session.flush()
        await session.refresh(default_session)
        await session.commit()
        logger.info(t("scripts.new_agent.session_created"), session_id, default_session.id)
        return session_id


async def save_soul_to_db(agent_db_id: int, soul_content: str) -> None:
    """將 SOUL.md 儲存至 memory_block 表。"""
    async with async_session_factory() as session:
        memory_block = MemoryBlock(
            agent_id=agent_db_id,
            memory_type="SOUL",
            content=soul_content,
            last_upd_dt=datetime.now(timezone.utc),
        )
        session.add(memory_block)
        await session.flush()
        await session.refresh(memory_block)
        await session.commit()
        logger.info(t("scripts.new_agent.soul_saved"), memory_block.id)


async def init_db() -> None:
    """套用資料庫 migration，確保 schema 與 ORM model 一致。"""
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """主流程：收集輸入 -> Bootstrap 對話 -> 儲存至 DB。"""
    print("=" * 60)
    print(t("scripts.new_agent.title"))
    print("=" * 60)
    print()

    # Step 1: Get agent name
    agent_name = input(t("scripts.new_agent.enter_agent_name")).strip()
    if not agent_name:
        print(t("scripts.new_agent.agent_name_empty"))
        sys.exit(1)

    # Step 2: Get user name (for DB)
    user_name = input(t("scripts.new_agent.enter_user_name")).strip()
    if not user_name:
        user_name = "default_user"

    # Step 3: Select agent type
    print()
    print(t("scripts.new_agent.select_agent_type"))
    print("  1) agent")
    print("  2) supervisor")
    type_choice = input(t("scripts.new_agent.enter_option")).strip()
    if type_choice == "2":
        agent_type = "supervisor"
    else:
        agent_type = "agent"
    print(t("scripts.new_agent.agent_type_selected") % agent_type)
    print()
    print(t("scripts.new_agent.init_db"))
    await init_db()

    try:
        # Ensure user exists
        user_db_id = await ensure_user_exists(user_name)
        llm_group_id = await ensure_llm_group_exists(user_db_id)

        # Create agent record
        import uuid

        agent_uuid = str(uuid.uuid4())
        agent_id_str = f"agent-{agent_uuid}"
        agent_db_id = await create_agent_in_db(
            user_db_id,
            llm_group_id,
            agent_id_str,
            agent_name,
            agent_type,
        )

        # Create default session
        session_id = await create_default_session(agent_db_id, agent_uuid)

        # Run bootstrap conversation
        soul_content = await run_bootstrap_conversation(agent_name)

        # Save SOUL.md to DB
        await save_soul_to_db(agent_db_id, soul_content)

        print()
        print("=" * 60)
        print(t("scripts.new_agent.complete"))
        print(f"   {t('scripts.new_agent.name')}: {agent_name}")
        print(f"   {t('scripts.new_agent.agent_id')}: {agent_id_str}")
        print(f"   {t('scripts.new_agent.agent_type')}: {agent_type}")
        print(f"   {t('scripts.new_agent.session_id')}: {session_id}")
        print(f"   SOUL.md: {t('scripts.new_agent.soul_status')}")
        print("=" * 60)

    except KeyboardInterrupt:
        print(t("scripts.new_agent.operation_cancelled"))
        sys.exit(130)
    except Exception as e:
        logger.error(t("scripts.new_agent.error_creating_agent"), e, exc_info=True)
        print(f"\n{t('scripts.new_agent.error')}: {e}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
