#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
清理 LangGraph checkpoint 記錄及（可選）agent_messages 記錄。

用法:
    python scripts/cleanup_checkpoints.py
    python scripts/cleanup_checkpoints.py --delete-messages
    python scripts/cleanup_checkpoints.py --dry-run
    python scripts/cleanup_checkpoints.py --delete-messages --dry-run
    python scripts/cleanup_checkpoints.py --help
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 加入專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from db import create_engine, AsyncSession
from i18n import _


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def print_divider(title: str = "") -> None:
    """列印分隔線，可選標題。"""
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


async def count_records(session: AsyncSession, table_name: str) -> int:
    """計算指定表的記錄數量。

    Args:
        session: 資料庫 session
        table_name: 表名稱

    Returns:
        記錄數量
    """
    result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    count = result.scalar()
    return count or 0


async def delete_all_records(session: AsyncSession, table_name: str) -> int:
    """刪除指定表的所有記錄。

    Args:
        session: 資料庫 session
        table_name: 表名稱

    Returns:
        刪除的記錄數量
    """
    result = await session.execute(text(f"DELETE FROM {table_name}"))
    return result.rowcount


# ─────────────────────────────────────────────
# 主要邏輯
# ─────────────────────────────────────────────

async def cleanup_checkpoints(delete_messages: bool = False, dry_run: bool = False) -> None:
    """清理 LangGraph checkpoint 記錄及（可選）agent_messages 記錄。

    Args:
        delete_messages: 是否刪除 agent_messages 表的所有記錄（預設: False）
        dry_run: 是否僅預覽而不實際刪除（預設: False）
    """
    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            if dry_run:
                print_divider(_("預覽模式（不會實際刪除）"))
            else:
                print_divider(_("清理開始"))

            # ── 1. 清理 checkpoint 相關表 ───────────────────────────
            # LangGraph checkpoint 表位於 langgraph schema
            checkpoint_tables = [
                "langgraph.checkpoint_writes",
                "langgraph.checkpoint_blobs",
                "langgraph.checkpoints",
            ]

            print_divider(_("1. 清理 LangGraph Checkpoint 表"))

            total_deleted = 0
            for table in checkpoint_tables:
                # 先計算記錄數量
                count_before = await count_records(session, table)
                # 顯示時只顯示表名，不顯示 schema
                table_display = table.split(".")[-1]
                print(f"  📊 {table_display}: {count_before} {_('筆記錄')}")

                if count_before > 0:
                    if not dry_run:
                        # 刪除所有記錄
                        deleted = await delete_all_records(session, table)
                        total_deleted += deleted
                        print(f"  ✅ {table_display}: {_('已刪除')} {deleted} {_('筆記錄')}")
                    else:
                        total_deleted += count_before
                        print(f"  🔍 {table_display}: {_('將刪除')} {count_before} {_('筆記錄')}")
                else:
                    print(f"  ℹ️  {table_display}: {_('無需清理')}")

            if not dry_run:
                await session.commit()
                print(f"\n  🗑️  {_('Checkpoint 表共刪除')}: {total_deleted} {_('筆記錄')}")
            else:
                print(f"\n  🔍 {_('Checkpoint 表將刪除')}: {total_deleted} {_('筆記錄')}")

            # ── 2. 可選：清理 agent_messages 表 ────────────────────
            # agent_messages 表位於 public schema (預設)
            if delete_messages:
                print_divider(_("2. 清理 Agent Messages 表"))

                count_before = await count_records(session, "public.agent_messages")
                print(f"  📊 agent_messages: {count_before} {_('筆記錄')}")

                if count_before > 0:
                    if not dry_run:
                        deleted = await delete_all_records(session, "public.agent_messages")
                        await session.commit()
                        print(f"  ✅ agent_messages: {_('已刪除')} {deleted} {_('筆記錄')}")
                    else:
                        print(f"  🔍 agent_messages: {_('將刪除')} {count_before} {_('筆記錄')}")
                else:
                    print(f"  ℹ️  agent_messages: {_('無需清理')}")
            else:
                print_divider(_("2. 保留 Agent Messages 表"))
                count_before = await count_records(session, "public.agent_messages")
                print(f"  ℹ️  agent_messages: {count_before} {_('筆記錄')} ({_('未刪除')})")

            # ── 摘要 ───────────────────────────────────────────────
            print_divider(_("摘要"))
            if not dry_run:
                print(f"  ✅ {_('Checkpoint 表已清空')}")
                if delete_messages:
                    print(f"  ✅ {_('Agent Messages 表已清空')}")
                else:
                    print(f"  ℹ️  {_('Agent Messages 表保持不變')}")
                print_divider()
                print(f"  ✅ {_('清理完成！')}")
            else:
                print(f"  🔍 {_('Checkpoint 表將被清空')}")
                if delete_messages:
                    print(f"  🔍 {_('Agent Messages 表將被清空')}")
                else:
                    print(f"  ℹ️  {_('Agent Messages 表將保持不變')}")
                print_divider()
                print(f"  ℹ️  {_('這是預覽模式，未實際執行刪除操作')}")
                print(f"  💡 {_('如需執行實際刪除，請移除 --dry-run 選項')}")

    except Exception as e:
        print(f"\n  ❌ {_('清理過程發生錯誤')}: {e}")
        raise
    finally:
        await engine.dispose()


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(
        description=_("清理 LangGraph checkpoint 記錄及（可選）agent_messages 記錄"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--delete-messages",
        action="store_true",
        help=_("同時刪除 agent_messages 表的所有記錄（預設: 不刪除）"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=_("預覽模式，顯示將刪除的記錄數量但不實際執行刪除（預設: 關閉）"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(cleanup_checkpoints(
        delete_messages=args.delete_messages,
        dry_run=args.dry_run
    ))
