#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
刪除手動創建的 checkpoint 表（public schema）。

這些表已被 LangGraph 的自動創建表（langgraph schema）取代。

用法:
    python scripts/drop_manual_checkpoint_tables.py
    python scripts/drop_manual_checkpoint_tables.py --dry-run
    python scripts/drop_manual_checkpoint_tables.py --help
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


async def table_exists(session: AsyncSession, schema: str, table_name: str) -> bool:
    """檢查表是否存在。

    Args:
        session: 資料庫 session
        schema: Schema 名稱
        table_name: 表名稱

    Returns:
        表是否存在
    """
    result = await session.execute(
        text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = :schema
                AND table_name = :table_name
            )
            """
        ),
        {"schema": schema, "table_name": table_name}
    )
    return result.scalar() or False


async def drop_table(session: AsyncSession, schema: str, table_name: str) -> None:
    """刪除表。

    Args:
        session: 資料庫 session
        schema: Schema 名稱
        table_name: 表名稱
    """
    await session.execute(text(f'DROP TABLE IF EXISTS "{schema}".{table_name} CASCADE'))


# ─────────────────────────────────────────────
# 主要邏輯
# ─────────────────────────────────────────────

async def drop_manual_checkpoint_tables(dry_run: bool = False) -> None:
    """刪除手動創建的 checkpoint 表。

    Args:
        dry_run: 是否僅預覽而不實際刪除（預設: False）
    """
    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 這些表是在 public schema 中手動創建的，已被 langgraph schema 的表取代
    tables_to_drop = [
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
    ]

    try:
        async with session_factory() as session:
            if dry_run:
                print_divider(_("預覽模式（不會實際刪除）"))
            else:
                print_divider(_("刪除手動創建的 Checkpoint 表"))

            print(f"\n  ℹ️  {_('這些表位於 public schema，將被刪除：')}")
            for table in tables_to_drop:
                print(f"     - public.{table}")

            print(f"\n  ℹ️  {_('LangGraph 使用的表（langgraph schema）不受影響')}\n")

            # 檢查並刪除每個表
            dropped_count = 0
            for table in tables_to_drop:
                exists = await table_exists(session, "public", table)

                if exists:
                    if not dry_run:
                        await drop_table(session, "public", table)
                        print(f"  ✅ {_('已刪除')}: public.{table}")
                    else:
                        print(f"  🔍 {_('將刪除')}: public.{table}")
                    dropped_count += 1
                else:
                    print(f"  ℹ️  {_('不存在')}: public.{table}")

            if not dry_run:
                await session.commit()
                print_divider(_("完成"))
                if dropped_count > 0:
                    print(f"  ✅ {_('已刪除')} {dropped_count} {_('個表')}")
                else:
                    print(f"  ℹ️  {_('無需刪除任何表')}")
            else:
                print_divider(_("預覽摘要"))
                if dropped_count > 0:
                    print(f"  🔍 {_('將刪除')} {dropped_count} {_('個表')}")
                    print(f"\n  💡 {_('如需執行實際刪除，請移除 --dry-run 選項')}")
                else:
                    print(f"  ℹ️  {_('無需刪除任何表')}")

            print_divider()

    except Exception as e:
        print(f"\n  ❌ {_('刪除過程發生錯誤')}: {e}")
        raise
    finally:
        await engine.dispose()


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(
        description=_("刪除手動創建的 checkpoint 表（public schema）"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=_("預覽模式，顯示將刪除的表但不實際執行刪除（預設: 關閉）"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(drop_manual_checkpoint_tables(dry_run=args.dry_run))
