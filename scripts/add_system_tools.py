#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
將系統工具（system / agent / web）註冊到工具資料庫。

包含以下工具：
  系統/檔案工具  : read, write, edit, apply_patch, grep, find, ls, exec, process
  Web 工具      : web_search, web_fetch
  Agent 工具    : agents_list, sessions_history, sessions_send, sessions_spawn,
                  session_status

用法:
    python scripts/add_system_tools.py
    python scripts/add_system_tools.py --agent-type-name "管家Agent"
    python scripts/add_system_tools.py --help
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
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.agent_tool_dao import AgentTypeToolDAO
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from db.dto.agent_tool_dto import AgentTypeToolCreate
from db.dto.tool_dto import ToolCreate, ToolVersionCreate


TOOLS = [
    # -----------------------------------------------------------------------
    # Filesystem / shell tools
    # -----------------------------------------------------------------------
    {
        "name": "read",
        "description": "讀取檔案內容。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "絕對或相對檔案路徑",
                },
                "encoding": {
                    "type": "string",
                    "description": "文字編碼（預設：utf-8）",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        },
        "implementation_ref": "tools.system_tools:read_impl",
    },
    {
        "name": "write",
        "description": "建立或覆寫檔案。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "絕對或相對檔案路徑",
                },
                "content": {
                    "type": "string",
                    "description": "要寫入的文字內容",
                },
                "encoding": {
                    "type": "string",
                    "description": "文字編碼（預設：utf-8）",
                    "default": "utf-8",
                },
            },
            "required": ["path", "content"],
        },
        "implementation_ref": "tools.system_tools:write_impl",
    },
    {
        "name": "edit",
        "description": "對檔案進行精確的字串替換編輯。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要編輯的檔案路徑",
                },
                "old_string": {
                    "type": "string",
                    "description": "要搜索的精確文字",
                },
                "new_string": {
                    "type": "string",
                    "description": "替換文字",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替換所有出現（預設：False，只替換第一個）",
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        "implementation_ref": "tools.system_tools:edit_impl",
    },
    {
        "name": "apply_patch",
        "description": "將 unified diff patch 套用到一個或多個檔案。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Unified diff 格式的 patch 文字",
                },
                "strip": {
                    "type": "integer",
                    "description": "要去掉的路徑前綴層數（patch -p，預設：1）",
                    "default": 1,
                },
            },
            "required": ["patch"],
        },
        "implementation_ref": "tools.system_tools:apply_patch_impl",
    },
    {
        "name": "grep",
        "description": "在檔案內容中搜索正則表達式模式。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "要搜索的正則表達式",
                },
                "path": {
                    "type": "string",
                    "description": "要搜索的檔案或目錄路徑（預設：當前目錄）",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "是否遞歸搜索子目錄（預設：True）",
                    "default": True,
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "是否忽略大小寫（預設：False）",
                    "default": False,
                },
                "include": {
                    "type": "string",
                    "description": "過濾檔案名的 glob 模式（如 *.py）",
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回的結果行數（預設：100）",
                    "default": 100,
                },
            },
            "required": ["pattern"],
        },
        "implementation_ref": "tools.system_tools:grep_impl",
    },
    {
        "name": "find",
        "description": "按 glob 模式查找檔案。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob 模式（如 **/*.py、src/*.ts）",
                },
                "path": {
                    "type": "string",
                    "description": "搜索的根目錄（預設：當前目錄）",
                    "default": ".",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回的結果數（預設：200）",
                    "default": 200,
                },
            },
            "required": ["pattern"],
        },
        "implementation_ref": "tools.system_tools:find_impl",
    },
    {
        "name": "ls",
        "description": "列出目錄內容。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要列出的目錄路徑（預設：當前目錄）",
                    "default": ".",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "是否顯示隱藏檔案（以 . 開頭，預設：False）",
                    "default": False,
                },
            },
            "required": [],
        },
        "implementation_ref": "tools.system_tools:ls_impl",
    },
    {
        "name": "exec",
        "description": "執行 shell 命令並返回輸出（支援 PTY 的 TTY 命令）。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要執行的 shell 命令字符串",
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目錄（可選）",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超時秒數（最大 300，預設：60）",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
        "implementation_ref": "tools.system_tools:exec_impl",
    },
    {
        "name": "process",
        "description": "管理後台 shell 進程會話（啟動、查詢狀態、終止、列出）。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作類型：start、status、kill、list",
                },
                "command": {
                    "type": "string",
                    "description": "要啟動的 shell 命令（action=start 時必填）",
                    "default": "",
                },
                "handle": {
                    "type": "string",
                    "description": "start 返回的進程 handle（action=status/kill 時必填）",
                    "default": "",
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目錄（action=start 時可選）",
                    "default": "",
                },
            },
            "required": ["action"],
        },
        "implementation_ref": "tools.system_tools:process_impl",
    },
    # -----------------------------------------------------------------------
    # Cron / scheduled task tools
    # -----------------------------------------------------------------------
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
    # -----------------------------------------------------------------------
    # Web tools
    # -----------------------------------------------------------------------
    {
        "name": "web_search",
        "description": "使用 DuckDuckGo 搜索網絡。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查詢字符串",
                },
                "num_results": {
                    "type": "integer",
                    "description": "要返回的結果數量（預設：5，最大：10）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "implementation_ref": "tools.web_search:execute_web_search",
    },
    {
        "name": "web_fetch",
        "description": "抓取 URL 並提取可讀的文字內容。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的 URL",
                },
                "max_length": {
                    "type": "integer",
                    "description": "返回文字的最大字符數（預設：5000）",
                    "default": 5000,
                },
            },
            "required": ["url"],
        },
        "implementation_ref": "tools.web_search:execute_web_fetch",
    },
    # -----------------------------------------------------------------------
    # Agent / session tools
    # -----------------------------------------------------------------------
    {
        "name": "agents_list",
        "description": "列出同一用戶下所有 sub-agent（is_sub_agent=True）的資訊。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "implementation_ref": "tools.agent_tools:agents_list_impl",
    },
    {
        "name": "sessions_history",
        "description": "獲取另一個 session / sub-agent 的對話歷史記錄。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "協作 session 的 session_id（如 session-<uuid>）",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回的訊息數（預設：50）",
                    "default": 50,
                },
            },
            "required": ["session_id"],
        },
        "implementation_ref": "tools.agent_tools:sessions_history_impl",
    },
    {
        "name": "sessions_send",
        "description": "透過協作 session 向另一個 agent 發送訊息。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "協作 session 的 session_id",
                },
                "content": {
                    "type": "string",
                    "description": "要發送的訊息內容",
                },
                "receiver_agent_id": {
                    "type": "string",
                    "description": "接收 agent 的 UUID（可選，空表示廣播）",
                    "default": "",
                },
                "sender_agent_id": {
                    "type": "string",
                    "description": (
                        "發送 agent 的 UUID（可選，"
                        "不填則使用當前 agent）"
                    ),
                    "default": "",
                },
                "message_type": {
                    "type": "string",
                    "description": (
                        "訊息類型：request、response、notification、"
                        "ack、tool_call、tool_result（預設：request）"
                    ),
                    "default": "request",
                },
            },
            "required": ["session_id", "content"],
        },
        "implementation_ref": "tools.agent_tools:sessions_send_impl",
    },
    {
        "name": "sessions_spawn",
        "description": "與目標 agent 建立新的協作 session。",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_agent_id": {
                    "type": "string",
                    "description": "目標 agent 實例的 UUID",
                },
                "session_name": {
                    "type": "string",
                    "description": "Session 名稱（可選）",
                    "default": "",
                },
            },
            "required": ["to_agent_id"],
        },
        "implementation_ref": "tools.agent_tools:sessions_spawn_impl",
    },
    {
        "name": "session_status",
        "description": (
            "顯示當前 agent 的狀態卡（用量、時間、模型資訊）；"
            "適用於模型用量查詢（📊 session_status）。"
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "implementation_ref": "tools.agent_tools:session_status_impl",
    },
]


def print_divider(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


async def add_system_tools(agent_type_name: str | None = None) -> None:
    """將所有系統工具註冊到 DB，並可選擇關聯到指定 Agent Type。

    Args:
        agent_type_name: Agent Type 名稱（若提供，會自動關聯所有工具）
    """
    engine = create_engine()
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    created_tools = []

    try:
        async with session_factory() as session:
            for tool_def in TOOLS:
                print_divider(tool_def["name"])

                # 1. 建立或取得 Tool
                existing_tool = await ToolDAO.get_by_name(
                    tool_def["name"], session=session
                )
                if existing_tool:
                    print("  ℹ️  Tool 已存在，使用現有 Tool")
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
                    print("  ✅ Tool 已建立")

                print(f"     Tool ID  : {tool.id}")

                # 2. 建立或取得 ToolVersion
                existing_versions = await ToolVersionDAO.get_by_tool_id(
                    tool.id, session=session
                )
                if existing_versions:
                    print("  ℹ️  已存在版本，跳過建立")
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
                    print("  ✅ ToolVersion 已建立")

                print(f"     Version  : {tool_version.version}")
                print(f"     Ref      : {tool_version.implementation_ref}")
                created_tools.append((tool, tool_version))

            # 3. 關聯到 Agent Type（如果有指定）
            if agent_type_name:
                print_divider(f"關聯到 Agent Type: {agent_type_name}")
                agent_type = await AgentTypeDAO.get_by_name(
                    agent_type_name, session=session
                )

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
        print(f"  ✅ 共處理 {len(created_tools)} 個工具")

    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="將系統工具（system / agent / web）註冊到工具資料庫",
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
    asyncio.run(add_system_tools(agent_type_name=args.agent_type_name))
