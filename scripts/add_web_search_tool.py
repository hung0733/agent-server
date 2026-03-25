#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
建立 Web Search Tool 並關聯到指定 Agent Type。

用法:
    python scripts/add_web_search_tool.py
    python scripts/add_web_search_tool.py --agent-type-name "管家Agent"
    python scripts/add_web_search_tool.py --help
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

# 匯入 Entity
from db.entity.tool_entity import Tool as ToolEntity, ToolVersion as ToolVersionEntity
from db.entity.agent_tool_entity import AgentTypeTool as AgentTypeToolEntity

# 匯入 DAOs 和 DTOs
from db import create_engine, AsyncSession
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.agent_tool_dao import AgentTypeToolDAO
from db.dto.tool_dto import ToolCreate, ToolVersionCreate
from db.dto.agent_tool_dto import AgentTypeToolCreate


# ─────────────────────────────────────────────
# Web Search Tool 定義
# ─────────────────────────────────────────────

WEB_SEARCH_TOOL_DEF = {
    "name": "web_search",
    "description": "Search the web for information using a search engine. Returns relevant search results with titles, snippets, and URLs.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to execute"
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10)",
                "default": 5,
                "minimum": 1,
                "maximum": 10
            }
        },
        "required": ["query"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                        "url": {"type": "string"}
                    }
                }
            },
            "query": {"type": "string"},
            "total_results": {"type": "integer"}
        }
    },
    "implementation_ref": "tools.web_search:execute_web_search",
    "config_json": {
        "search_engine": "duckduckgo",
        "timeout": 10,
        "safe_search": True
    }
}


def print_divider(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


async def add_web_search_tool(agent_type_name: str | None = None) -> None:
    """建立 Web Search Tool 並關聯到 Agent Type。

    Args:
        agent_type_name: Agent Type 名稱（如果提供，會自動關聯）
    """
    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # ── 1. 檢查 Tool 是否已存在 ────────────────────────────
            print_divider("1. 檢查 Web Search Tool")
            existing_tool = await ToolDAO.get_by_name(
                WEB_SEARCH_TOOL_DEF["name"], session=session
            )

            if existing_tool:
                print(f"  ℹ️  Tool 已存在，使用現有 Tool")
                tool = existing_tool
            else:
                # ── 2. 建立 Tool ───────────────────────────────────
                print_divider("2. 建立 Web Search Tool")
                tool = await ToolDAO.create(
                    ToolCreate(
                        name=WEB_SEARCH_TOOL_DEF["name"],
                        description=WEB_SEARCH_TOOL_DEF["description"],
                        is_active=True,
                    ),
                    session=session,
                )
                print(f"  ✅ Tool 已建立")

            print(f"     Tool ID  : {tool.id}")
            print(f"     名稱     : {tool.name}")
            print(f"     說明     : {tool.description}")

            # ── 3. 建立 Tool Version ───────────────────────────
            print_divider("3. 建立 Tool Version")

            # 檢查是否已有版本
            from db.dao.tool_version_dao import ToolVersionDAO
            existing_versions = await ToolVersionDAO.get_by_tool_id(
                tool.id, session=session
            )

            if existing_versions:
                print(f"  ℹ️  已存在 {len(existing_versions)} 個版本，跳過建立")
                tool_version = existing_versions[0]
            else:
                tool_version = await ToolVersionDAO.create(
                    ToolVersionCreate(
                        tool_id=tool.id,
                        version=WEB_SEARCH_TOOL_DEF["version"],
                        input_schema=WEB_SEARCH_TOOL_DEF["input_schema"],
                        output_schema=WEB_SEARCH_TOOL_DEF["output_schema"],
                        implementation_ref=WEB_SEARCH_TOOL_DEF["implementation_ref"],
                        config_json=WEB_SEARCH_TOOL_DEF["config_json"],
                        is_default=True,
                    ),
                    session=session,
                )
                print(f"  ✅ Tool Version 已建立")

            print(f"     Version ID : {tool_version.id}")
            print(f"     版本       : {tool_version.version}")
            print(f"     預設版本   : {tool_version.is_default}")

            # ── 4. 關聯到 Agent Type（如果有指定）─────────────────
            if agent_type_name:
                print_divider(f"4. 關聯到 Agent Type: {agent_type_name}")

                # 查找 Agent Type
                agent_type = await AgentTypeDAO.get_by_name(
                    agent_type_name, session=session
                )

                if not agent_type:
                    print(f"  ❌ 找不到 Agent Type: {agent_type_name}")
                    print(f"     請先建立 Agent Type 或檢查名稱")
                else:
                    # 檢查是否已關聯
                    is_assigned = await AgentTypeToolDAO.is_assigned(
                        agent_type.id, tool.id, session=session
                    )

                    if is_assigned:
                        print(f"  ℹ️  Tool 已關聯到此 Agent Type")
                        # 獲取關聯詳情
                        tools_for_type = await AgentTypeToolDAO.get_tools_for_type(
                            agent_type.id, session=session
                        )
                        assoc = next((t for t in tools_for_type if t.tool_id == tool.id), None)
                    else:
                        # 建立關聯
                        assoc = await AgentTypeToolDAO.assign(
                            AgentTypeToolCreate(
                                agent_type_id=agent_type.id,
                                tool_id=tool.id,
                                is_active=True,
                            ),
                            session=session,
                        )
                        print(f"  ✅ Tool 已關聯到 Agent Type")

                    if assoc:
                        print(f"     Association ID : {assoc.id}")
                        print(f"     Agent Type     : {agent_type.name}")
                        print(f"     Tool           : {tool.name}")
                        print(f"     啟用           : {assoc.is_active}")

        # ── 摘要 ───────────────────────────────────────────────
        print_divider("摘要")
        print(f"  Tool ID         : {tool.id}")
        print(f"  Tool Name       : {tool.name}")
        print(f"  Version ID      : {tool_version.id}")
        if agent_type_name and agent_type:
            print(f"  Agent Type      : {agent_type.name}")
            print(f"  已關聯          : ✅")
        print_divider()
        print("  ✅ Web Search Tool 設定完成！")
        print("")
        print("  💡 下一步：")
        print("     1. 實作 tools/web_search.py 中的 execute_web_search 函數")
        print("     2. 重啟應用程式以載入新 tool")

    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="建立 Web Search Tool 並關聯到 Agent Type",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--agent-type-name",
        default="管家Agent",
        help="要關聯的 Agent Type 名稱（預設: 管家Agent）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(add_web_search_tool(agent_type_name=args.agent_type_name))
