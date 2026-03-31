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
        "description": "Read the full text content of a file from the filesystem.",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read.",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding to use when reading the file (default: utf-8).",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        },
        "implementation_ref": "tools.system_tools:read_impl",
    },
    {
        "name": "write",
        "description": (
            "Create a new file or completely overwrite an existing file with the given content. "
            "Parent directories are created automatically if they do not exist."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path where the file should be written.",
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write to the file.",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding to use when writing the file (default: utf-8).",
                    "default": "utf-8",
                },
            },
            "required": ["path", "content"],
        },
        "implementation_ref": "tools.system_tools:write_impl",
    },
    {
        "name": "edit",
        "description": (
            "Make a precise string replacement inside an existing file. "
            "Finds an exact occurrence of old_string and replaces it with new_string. "
            "Use replace_all=true to replace every occurrence instead of just the first."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to search for in the file. Must match character-for-character.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text that will substitute old_string.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace every occurrence of old_string; if false (default), replace only the first.",
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        "implementation_ref": "tools.system_tools:edit_impl",
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a unified diff patch to one or more files using the system patch command. "
            "Useful for making multi-file changes expressed as a git diff or diff -u output."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Unified diff text to apply (as produced by git diff or diff -u).",
                },
                "strip": {
                    "type": "integer",
                    "description": "Number of leading path components to strip from file paths in the patch (patch -p flag, default: 1).",
                    "default": 1,
                },
            },
            "required": ["patch"],
        },
        "implementation_ref": "tools.system_tools:apply_patch_impl",
    },
    {
        "name": "grep",
        "description": (
            "Search file contents for lines matching a regular expression pattern. "
            "Returns matching lines in file:line_number:content format."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in. Defaults to the current working directory.",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to search subdirectories recursively (default: true).",
                    "default": True,
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Whether to perform case-insensitive matching (default: false).",
                    "default": False,
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to restrict which files are searched, e.g. '*.py' or '*.{ts,tsx}'.",
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 100).",
                    "default": 100,
                },
            },
            "required": ["pattern"],
        },
        "implementation_ref": "tools.system_tools:grep_impl",
    },
    {
        "name": "find",
        "description": (
            "Find files whose paths match a glob pattern. "
            "Returns a newline-separated list of matching file paths sorted by modification time."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match against file paths, e.g. '**/*.py' or 'src/**/*.ts'.",
                },
                "path": {
                    "type": "string",
                    "description": "Root directory to search from (default: current working directory).",
                    "default": ".",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching paths to return (default: 200).",
                    "default": 200,
                },
            },
            "required": ["pattern"],
        },
        "implementation_ref": "tools.system_tools:find_impl",
    },
    {
        "name": "ls",
        "description": "List the files and subdirectories inside a directory, with file sizes.",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list (default: current working directory).",
                    "default": ".",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Whether to include hidden entries whose names start with a dot (default: false).",
                    "default": False,
                },
            },
            "required": [],
        },
        "implementation_ref": "tools.system_tools:ls_impl",
    },
    {
        "name": "exec",
        "description": (
            "Run a shell command and return its combined stdout + stderr output along with the exit code. "
            "Use for one-shot commands; for long-running background processes use the process tool instead."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command string to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory in which to run the command. Defaults to the agent's base_dir config or the server's cwd.",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for the command to finish (capped at 300, default: 60).",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
        "implementation_ref": "tools.system_tools:exec_impl",
    },
    {
        "name": "process",
        "description": (
            "Manage long-running background shell processes. "
            "Use action='start' to launch a command in the background and receive a handle, "
            "then 'status' to check whether it is still running, "
            "'kill' to terminate it, or 'list' to see all background processes."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Operation to perform: 'start' (launch a background command), 'status' (check if running), 'kill' (terminate), or 'list' (show all active processes).",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run in the background. Required when action is 'start'.",
                    "default": "",
                },
                "handle": {
                    "type": "string",
                    "description": "Process handle returned by a previous 'start' call. Required for 'status' and 'kill' actions.",
                    "default": "",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the background process. Used only when action is 'start'.",
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
        "description": (
            "Create a new scheduled task that will automatically send a prompt to this agent "
            "at the specified schedule. Supports cron expressions, fixed intervals, and one-time execution."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt message that will be sent to the agent each time the schedule fires.",
                },
                "schedule_expression": {
                    "type": "string",
                    "description": (
                        "Schedule definition whose format depends on schedule_type: "
                        "cron uses standard 5-field cron syntax e.g. '0 12 * * *' (daily at noon); "
                        "interval uses ISO 8601 duration e.g. 'PT1H' (every hour) or 'P1D' (daily); "
                        "once uses an ISO 8601 datetime e.g. '2026-03-26T12:00:00Z' (run once at that time)."
                    ),
                },
                "schedule_type": {
                    "type": "string",
                    "description": "Type of schedule: 'cron' for recurring cron expressions, 'interval' for fixed time intervals, or 'once' for a single future execution (default: cron).",
                    "default": "cron",
                },
                "task_name": {
                    "type": "string",
                    "description": "Optional human-readable name for the task shown in listings.",
                    "default": "",
                },
            },
            "required": ["prompt", "schedule_expression"],
        },
        "implementation_ref": "tools.task_schedule_tools:create_scheduled_task_impl",
    },
    {
        "name": "list_my_cron_tasks",
        "description": (
            "List all scheduled tasks belonging to this agent, including their schedule type, "
            "expression, next run time, and enabled/disabled status."
        ),
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
        "description": (
            "Update an existing scheduled task owned by this agent. "
            "Can change the prompt, the schedule expression, or enable/disable the task. "
            "Only provide the fields you want to change."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UUID of the scheduled task to update.",
                },
                "prompt": {
                    "type": "string",
                    "description": "New prompt to send when the task fires. Omit to keep the current prompt.",
                },
                "schedule_expression": {
                    "type": "string",
                    "description": "New schedule expression in the same format as create_cron_task. Omit to keep the current schedule.",
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Set to true to enable the task or false to disable it without deleting it.",
                },
            },
            "required": ["task_id"],
        },
        "implementation_ref": "tools.task_schedule_tools:update_my_scheduled_task_impl",
    },
    {
        "name": "delete_my_cron_task",
        "description": (
            "Permanently delete a scheduled task owned by this agent. "
            "This also removes its associated schedule. Use update_my_cron_task with is_active=false to disable without deleting."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UUID of the scheduled task to delete.",
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
        "description": (
            "Search the web using DuckDuckGo and return a ranked list of results with titles, "
            "snippets, and URLs. Use this to look up current information or verify facts."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string.",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5, max: 10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "implementation_ref": "tools.web_search:execute_web_search",
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a URL and extract its readable plain-text content, stripping HTML tags, "
            "scripts, and styles. Use this to read the full content of a specific page found via web_search."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum number of characters to return from the extracted text (default: 5000).",
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
        "description": (
            "List all sub-agents (is_sub_agent=True) that belong to the same user as the calling agent. "
            "Returns each sub-agent's name, ID, current status, and agent type ID. "
            "Use this to discover available agents before spawning a collaboration session."
        ),
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
        "description": (
            "Fetch the message history of a collaboration session in chronological order. "
            "Each entry shows the timestamp, message type, sender agent ID, and content. "
            "Use this to catch up on what another agent has said or done in a shared session."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session_id string of the collaboration session to read, e.g. 'session-<uuid>'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of messages to return, ordered oldest-first (default: 50).",
                    "default": 50,
                },
            },
            "required": ["session_id"],
        },
        "implementation_ref": "tools.agent_tools:sessions_history_impl",
    },
    {
        "name": "sessions_send",
        "description": (
            "Send a message to another agent through an existing collaboration session. "
            "The message is stored in the session history and can be read by the receiver via sessions_history. "
            "Specify receiver_agent_id to target a specific agent, or leave blank to broadcast to all session participants."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session_id string of the collaboration session to send the message into.",
                },
                "content": {
                    "type": "string",
                    "description": "Text content of the message to send.",
                },
                "receiver_agent_id": {
                    "type": "string",
                    "description": "UUID of the agent instance that should receive the message. Leave empty to broadcast to all participants.",
                    "default": "",
                },
                "sender_agent_id": {
                    "type": "string",
                    "description": "UUID of the agent instance sending the message. Defaults to the calling agent when left empty.",
                    "default": "",
                },
                "message_type": {
                    "type": "string",
                    "description": "Semantic type of the message: 'request' (default), 'response', 'notification', 'ack', 'tool_call', or 'tool_result'.",
                    "default": "request",
                },
            },
            "required": ["session_id", "content"],
        },
        "implementation_ref": "tools.agent_tools:sessions_send_impl",
    },
    {
        "name": "sessions_spawn",
        "description": (
            "Create a new collaboration session between the calling agent and a target agent. "
            "Returns a session_id that can be used with sessions_send and sessions_history. "
            "Use agents_list first to discover available agent IDs."
        ),
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_agent_id": {
                    "type": "string",
                    "description": "UUID of the target agent instance to open a collaboration session with.",
                },
                "session_name": {
                    "type": "string",
                    "description": "Optional human-readable name for the session. Auto-generated from both agent names if omitted.",
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
            "Show a status card for the calling agent, including its name, current state, "
            "last heartbeat time, and the most recent token usage (input tokens, output tokens, model name). "
            "Use this to answer questions about model usage or to verify the agent is running correctly."
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
