#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
更新用戶電話號碼。

用法:
    python scripts/update_user_phone.py --username Hung --phone 85297548257
    python scripts/update_user_phone.py --user-id 7d8604d3-9387-47be-86ea-0f7bbf1014e7 --phone 85297548257
    python scripts/update_user_phone.py --help
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 加入專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker

from db.entity.user_entity import User as UserEntity
from db import create_engine, AsyncSession, async_sessionmaker
from db.dao.user_dao import UserDAO
from db.dto.user_dto import UserUpdate
from i18n import _


async def update_user_phone(
    username: str | None = None,
    user_id: str | None = None,
    phone: str | None = None,
) -> None:
    """更新用戶電話號碼。

    Args:
        username: 用戶名稱（二選一）
        user_id: 用戶 ID（二選一）
        phone: 電話號碼（國際格式，不含 +）
    """
    if not phone:
        raise ValueError(_("必須提供電話號碼"))

    if not username and not user_id:
        raise ValueError(_("必須提供 username 或 user_id"))

    engine = create_engine()
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 查找用戶
        if user_id:
            user = await UserDAO.get_by_id(user_id, session=session)
            if not user:
                print(_("找不到用戶 ID: %s") % user_id)
                return
        else:
            user = await UserDAO.get_by_username(username, session=session)  # type: ignore
            if not user:
                print(_("找不到用戶: %s") % username)
                return

        print(_("找到用戶:"))
        print(_("  ID: %s") % user.id)
        print(_("  用戶名: %s") % user.username)
        print(_("  目前電話: %s") % (user.phone_no or _("（未設定）")))
        print()

        # 更新電話號碼
        updated_user = await UserDAO.update(
            user.id,
            UserUpdate(phone_no=phone),
            session=session,
        )

        await session.commit()

        print(_("✓ 已更新電話號碼:"))
        print(_("  新電話: %s") % updated_user.phone_no)

    await engine.dispose()


async def list_all_users() -> None:
    """列出所有用戶及其電話號碼。"""
    engine = create_engine()
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        users = await UserDAO.list(session=session)

        if not users:
            print(_("數據庫中沒有用戶"))
            return

        print(_("所有用戶 (共 %d 個):") % len(users))
        print()
        for user in users:
            print(_("  用戶名: %s") % user.username)
            print(_("    ID: %s") % user.id)
            print(_("    Email: %s") % (user.email or _("（未設定）")))
            print(_("    電話: %s") % (user.phone_no or _("（未設定）")))
            print()

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=_("更新用戶電話號碼"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--username",
        type=str,
        help=_("用戶名稱"),
    )
    parser.add_argument(
        "--user-id",
        type=str,
        help=_("用戶 ID"),
    )
    parser.add_argument(
        "--phone",
        type=str,
        help=_("電話號碼（國際格式，不含 +，例如: 85297548257）"),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help=_("列出所有用戶"),
    )

    args = parser.parse_args()

    if args.list:
        asyncio.run(list_all_users())
    elif args.phone:
        asyncio.run(update_user_phone(
            username=args.username,
            user_id=args.user_id,
            phone=args.phone,
        ))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
