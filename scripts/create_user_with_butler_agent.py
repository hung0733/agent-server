#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
建立用戶、分配 Auth Key 及創建管家 Agent。

用法:
    python scripts/create_user_with_butler_agent.py
    python scripts/create_user_with_butler_agent.py --username alice --email alice@example.com
    python scripts/create_user_with_butler_agent.py --help
"""
import argparse
import asyncio
import hashlib
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

# 加入專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker

# 先匯入所有 Entity，確保 SQLAlchemy 關係映射正確解析
from db.entity.user_entity import User as UserEntity, APIKey as APIKeyEntity
from db.entity.agent_entity import AgentType as AgentTypeEntity, AgentInstance as AgentInstanceEntity

# 匯入 DAOs 和 DTOs
from db import create_engine, AsyncSession, async_sessionmaker
from db.dao.user_dao import UserDAO
from db.dao.api_key_dao import APIKeyDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dto.user_dto import UserCreate, APIKeyCreate
from db.dto.agent_dto import AgentTypeCreate, AgentInstanceCreate
from db.types import AgentStatus

# ─────────────────────────────────────────────
# 常數：管家 Agent 預設設定
# ─────────────────────────────────────────────
BUTLER_AGENT_TYPE_NAME = "管家Agent"

BUTLER_AGENT_TYPE_DEFAULTS = {
    "description": "智能管家 Agent，負責協調任務、管理日程及提供個人化服務。",
    "capabilities": {
        "task_management": True,
        "schedule_management": True,
        "reminder": True,
        "delegation": True,
        "multi_language": ["zh-HK", "zh-TW", "en"],
    },
    "default_config": {
        "locale": "zh-HK",
        "response_style": "formal",
        "proactive_suggestions": True,
    },
}


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def generate_api_key() -> tuple[str, str]:
    """生成隨機 API Key 並返回 (明文, SHA-256 雜湊值)。

    Returns:
        (plain_key, key_hash) — 明文只顯示一次，雜湊值儲存到資料庫。
    """
    plain = f"sk-{secrets.token_urlsafe(32)}"
    hashed = hashlib.sha256(plain.encode()).hexdigest()
    return plain, f"sha256:{hashed}"


def print_divider(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


# ─────────────────────────────────────────────
# 主要邏輯
# ─────────────────────────────────────────────

async def create_user_with_butler(
    username: str,
    email: str,
    key_name: str = "預設 API Key",
    agent_instance_name: str | None = None,
) -> None:
    """建立用戶、分配 Auth Key 並創建管家 Agent 實例。

    Args:
        username: 用戶名稱（唯一）
        email: 用戶電郵（唯一）
        key_name: API Key 的描述名稱
        agent_instance_name: Agent 實例名稱，預設為「{username} 的管家」
    """
    if agent_instance_name is None:
        agent_instance_name = f"{username} 的管家"

    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # ── 1. 建立用戶 ────────────────────────────────────────
            print_divider("1. 建立用戶")
            user = await UserDAO.create(
                UserCreate(username=username, email=email),
                session=session,
            )
            print(f"  ✅ 用戶已建立")
            print(f"     ID       : {user.id}")
            print(f"     用戶名稱 : {user.username}")
            print(f"     電郵     : {user.email}")
            print(f"     建立時間 : {user.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

            # ── 2. 生成並分配 Auth Key ─────────────────────────────
            print_divider("2. 分配 Auth Key")
            plain_key, key_hash = generate_api_key()
            api_key = await APIKeyDAO.create(
                APIKeyCreate(
                    user_id=user.id,
                    key_hash=key_hash,
                    name=key_name,
                ),
                session=session,
            )
            print(f"  ✅ Auth Key 已建立")
            print(f"     Key ID   : {api_key.id}")
            print(f"     名稱     : {api_key.name}")
            print(f"     明文 Key : {plain_key}")
            print(f"     ⚠️  請立即妥善保存上方明文 Key，此後將無法再次查閱。")

            # ── 3. 確保管家 AgentType 存在 ─────────────────────────
            print_divider("3. 確保管家 Agent 類型")
            existing_type = await AgentTypeDAO.get_by_name(
                BUTLER_AGENT_TYPE_NAME, session=session
            )
            if existing_type:
                agent_type = existing_type
                print(f"  ℹ️  Agent 類型已存在，跳過建立")
            else:
                agent_type = await AgentTypeDAO.create(
                    AgentTypeCreate(
                        name=BUTLER_AGENT_TYPE_NAME,
                        **BUTLER_AGENT_TYPE_DEFAULTS,
                    ),
                    session=session,
                )
                print(f"  ✅ Agent 類型已建立")
            print(f"     Type ID  : {agent_type.id}")
            print(f"     名稱     : {agent_type.name}")
            print(f"     說明     : {agent_type.description}")

            # ── 4. 建立管家 Agent 實例 ─────────────────────────────
            print_divider("4. 建立管家 Agent 實例")
            agent_instance = await AgentInstanceDAO.create(
                AgentInstanceCreate(
                    agent_type_id=agent_type.id,
                    user_id=user.id,
                    name=agent_instance_name,
                    status=AgentStatus.idle,
                    config={
                        "owner_username": username,
                        "locale": "zh-HK",
                    },
                ),
                session=session,
            )
            print(f"  ✅ 管家 Agent 實例已建立")
            print(f"     Instance ID : {agent_instance.id}")
            print(f"     名稱        : {agent_instance.name}")
            print(f"     狀態        : {agent_instance.status}")
            print(f"     建立時間    : {agent_instance.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # ── 摘要 ───────────────────────────────────────────────────
        print_divider("摘要")
        print(f"  用戶 ID        : {user.id}")
        print(f"  Auth Key ID    : {api_key.id}")
        print(f"  Agent Type ID  : {agent_type.id}")
        print(f"  Agent 實例 ID  : {agent_instance.id}")
        print_divider()
        print("  ✅ 全部資源已成功建立！")

    finally:
        await engine.dispose()


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="建立用戶、分配 Auth Key 及創建管家 Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="用戶名稱（預設: admin）",
    )
    parser.add_argument(
        "--email",
        default="admin@example.com",
        help="用戶電郵（預設: admin@example.com）",
    )
    parser.add_argument(
        "--key-name",
        default="預設 API Key",
        help="API Key 名稱（預設: 預設 API Key）",
    )
    parser.add_argument(
        "--agent-name",
        default=None,
        help="管家 Agent 實例名稱（預設: {username} 的管家）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        create_user_with_butler(
            username=args.username,
            email=args.email,
            key_name=args.key_name,
            agent_instance_name=args.agent_name,
        )
    )
