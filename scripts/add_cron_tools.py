#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
建立 Cron Tools 並關聯到指定 Agent Type。

用法:
    python scripts/add_cron_tools.py
    python scripts/add_cron_tools.py --agent-type-name "管家Agent"
    python scripts/add_cron_tools.py --help
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker

from db import create_engine, AsyncSession
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.agent_tool_dao import AgentTypeToolDAO
from db.dto.tool_dto import ToolCreate, ToolVersionCreate
from db.dto.agent_tool_dto import AgentTypeToolCreate


CRON_TOOLS = [
    {
        "name": "create_cron_task",
        "description": "建立新排程任務，定時發送 prompt 給 agent。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "排程執行時發送給 agent 的 prompt",
                },
                "schedule_expression": {
                    "type": "string",
                    "description": (
                        "排程表達式：cron 格式 \"0 12 * * *\"、"
                        "interval 格式 \"PT1H\" / \"P1D\"、"
                        "once 格式 \"2026-03-26T12:00:00Z\""
                    ),
                },
                "schedule_type": {
                    "type": "string",
                    "description": "排程類型：cron、interval 或 once（預設：cron）",
                    "default": "cron",
                },
                "task_name": {
                    "type": "string",
                    "description": "任務名稱（可選）",
                    "default": "",
                },
            },
            "required": ["prompt", "schedule_expression"],
        },
        "implementation_ref": "tools.task_schedule_tools:create_scheduled_task_impl",
    },
    {
        "name": "list_my_cron_tasks",
        "description": "列出此 Agent 的所有排程任務。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "implementation_ref": "tools.task_schedule_tools:list_my_scheduled_tasks_impl",
    },
    {
        "name": "update_my_cron_task",
        "description": "更新排程任務的 prompt、排程表達式或啟用狀態。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要更新的任務 ID",
                },
                "prompt": {
                    "type": "string",
                    "description": "新的 prompt（可選）",
                },
                "schedule_expression": {
                    "type": "string",
                    "description": "新的排程表達式（可選）",
                },
                "is_active": {
                    "type": "boolean",
                    "description": "啟用或停用任務（可選）",
                },
            },
            "required": ["task_id"],
        },
        "implementation_ref": "tools.task_schedule_tools:update_my_scheduled_task_impl",
    },
    {
        "name": "delete_my_cron_task",
        "description": "刪除排程任務。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要刪除的任務 ID",
                },
            },
            "required": ["task_id"],
        },
        "implementation_ref": "tools.task_schedule_tools:delete_my_scheduled_task_impl",
    },
]


def print_divider(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


async def add_cron_tools(agent_type_name: str | None = None) -> None:
    """建立 Cron Tools 並可選關聯到 Agent Type。

    Args:
        agent_type_name: Agent Type 名稱（如果提供，會自動關聯所有 cron tools）
    """
    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    created_tools = []

    try:
        async with session_factory() as session:
            for tool_def in CRON_TOOLS:
                print_divider(tool_def["name"])

                # 1. 建立或取得 Tool
                existing_tool = await ToolDAO.get_by_name(tool_def["name"], session=session)
                if existing_tool:
                    print(f"  ℹ️  Tool 已存在，使用現有 Tool")
                    tool = existing_tool
                else:
                    tool = await ToolDAO.create(
                        ToolCreate(
                            name=tool_def["name"],
                            description=tool_def["description"],
                            is_active=True,
                        ),
                        session=session,
                    )
                    print(f"  ✅ Tool 已建立")

                print(f"     Tool ID  : {tool.id}")

                # 2. 建立或取得 ToolVersion
                existing_versions = await ToolVersionDAO.get_by_tool_id(tool.id, session=session)
                if existing_versions:
                    print(f"  ℹ️  已存在版本，跳過建立")
                    tool_version = existing_versions[0]
                else:
                    tool_version = await ToolVersionDAO.create(
                        ToolVersionCreate(
                            tool_id=tool.id,
                            version=tool_def["version"],
                            input_schema=tool_def["input_schema"],
                            implementation_ref=tool_def["implementation_ref"],
                            is_default=True,
                        ),
                        session=session,
                    )
                    print(f"  ✅ ToolVersion 已建立")

                print(f"     Version  : {tool_version.version}")
                print(f"     Ref      : {tool_version.implementation_ref}")
                created_tools.append((tool, tool_version))

            # 3. 關聯到 Agent Type（如果有指定）
            if agent_type_name:
                print_divider(f"關聯到 Agent Type: {agent_type_name}")
                agent_type = await AgentTypeDAO.get_by_name(agent_type_name, session=session)

                if not agent_type:
                    print(f"  ❌ 找不到 Agent Type: {agent_type_name}")
                else:
                    for tool, _ in created_tools:
                        is_assigned = await AgentTypeToolDAO.is_assigned(
                            agent_type.id, tool.id, session=session
                        )
                        if is_assigned:
                            print(f"  ℹ️  {tool.name} 已關聯")
                        else:
                            await AgentTypeToolDAO.assign(
                                AgentTypeToolCreate(
                                    agent_type_id=agent_type.id,
                                    tool_id=tool.id,
                                    is_active=True,
                                ),
                                session=session,
                            )
                            print(f"  ✅ {tool.name} 已關聯")

        print_divider("完成")
        print(f"  ✅ 共建立 {len(created_tools)} 個 Cron Tools")

    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="建立 Cron Tools 並關聯到 Agent Type",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--agent-type-name",
        default=None,
        help="要關聯的 Agent Type 名稱（可選）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(add_cron_tools(agent_type_name=args.agent_type_name))
