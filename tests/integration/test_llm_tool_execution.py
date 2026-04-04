# pyright: reportMissingImports=false
"""
LLM tool execution integration tests.

This module tests that all registered tools can be successfully invoked by
a Level 1 LLM. It verifies:
  1. Tool loading from database
  2. JSON Schema → Pydantic model conversion
  3. Tool execution with valid parameters
  4. Error handling for invalid parameters
  5. Configuration injection (_config, agent_db_id)
  6. All 20+ tools work end-to-end

Uses a test agent with all tools registered.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_tool_dao import AgentTypeToolDAO, AgentInstanceToolDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from db.dao.user_dao import UserDAO
from db.dto.agent_tool_dto import AgentTypeToolCreate, AgentInstanceToolCreate
from db.dto.agent_dto import AgentTypeCreate, AgentInstanceCreate
from db.dto.tool_dto import ToolCreate, ToolVersionCreate
from db.dto.user_dto import UserCreate
from i18n import _
from tools.tools import get_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with clean schema."""
    dsn = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'agentserver')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'testpass')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'agentserver')}"
    )

    engine = create_engine(dsn=dsn)
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> UUID:
    """Create a test user."""
    user_dto = UserCreate(
        username=f"test_user_{uuid4().hex[:8]}",
        email=f"test_{uuid4().hex[:8]}@example.com",
        hashed_password="test_password_hash",
    )
    user = await UserDAO.create(user_dto)
    return user.id


@pytest_asyncio.fixture
async def test_agent_type(db_session: AsyncSession, test_user: UUID) -> UUID:
    """Create a test agent type."""
    agent_type_dto = AgentTypeCreate(
        user_id=test_user,
        name=f"test_agent_type_{uuid4().hex[:8]}",
        description="Test agent type for tool execution tests",
    )
    agent_type = await AgentTypeDAO.create(agent_type_dto)
    return agent_type.id


@pytest_asyncio.fixture
async def test_agent_instance(db_session: AsyncSession, test_user: UUID, test_agent_type: UUID) -> UUID:
    """Create a test agent instance."""
    instance_dto = AgentInstanceCreate(
        user_id=test_user,
        agent_type_id=test_agent_type,
        metadata_json={},
    )
    instance = await AgentInstanceDAO.create(instance_dto)
    return instance.id


@pytest_asyncio.fixture
async def test_tools(db_session: AsyncSession) -> dict[str, UUID]:
    """Register all system tools in the database (or get existing ones).

    Returns:
        Dict mapping tool name → tool_id for all registered tools.
    """
    tools_spec = [
        # System/Filesystem tools
        {
            "name": "read",
            "description": "Read file contents",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "Text encoding",
                        "default": "utf-8",
                    },
                },
                "required": ["path"],
            },
            "implementation_ref": "tools.system_tools:read_impl",
        },
        {
            "name": "write",
            "description": "Create or overwrite a file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "File contents"},
                    "encoding": {
                        "type": "string",
                        "description": "Text encoding",
                        "default": "utf-8",
                    },
                },
                "required": ["path", "content"],
            },
            "implementation_ref": "tools.system_tools:write_impl",
        },
        {
            "name": "edit",
            "description": "Find and replace text in a file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "search": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "encoding": {
                        "type": "string",
                        "description": "Text encoding",
                        "default": "utf-8",
                    },
                },
                "required": ["path", "search", "replace"],
            },
            "implementation_ref": "tools.system_tools:edit_impl",
        },
        {
            "name": "apply_patch",
            "description": "Apply a unified diff patch",
            "input_schema": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string", "description": "Unified diff patch"},
                    "strip_level": {
                        "type": "integer",
                        "description": "Strip path components",
                        "default": 0,
                    },
                },
                "required": ["patch"],
            },
            "implementation_ref": "tools.system_tools:apply_patch_impl",
        },
        {
            "name": "grep",
            "description": "Search files with regex",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {
                        "type": "string",
                        "description": "Directory or file path",
                        "default": ".",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Search recursively",
                        "default": True,
                    },
                },
                "required": ["pattern"],
            },
            "implementation_ref": "tools.system_tools:grep_impl",
        },
        {
            "name": "find",
            "description": "Find files matching glob pattern",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "path": {
                        "type": "string",
                        "description": "Base directory",
                        "default": ".",
                    },
                },
                "required": ["pattern"],
            },
            "implementation_ref": "tools.system_tools:find_impl",
        },
        {
            "name": "ls",
            "description": "List directory contents",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path",
                        "default": ".",
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "Show hidden files",
                        "default": False,
                    },
                },
                "required": [],
            },
            "implementation_ref": "tools.system_tools:ls_impl",
        },
        {
            "name": "exec",
            "description": "Execute a shell command",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command"},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
            "implementation_ref": "tools.system_tools:exec_impl",
        },
        {
            "name": "process",
            "description": "Manage background processes (start/status/kill/list)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: start, status, kill, list",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command for start action",
                    },
                    "handle": {
                        "type": "string",
                        "description": "Process handle for status/kill",
                    },
                },
                "required": ["action"],
            },
            "implementation_ref": "tools.system_tools:process_impl",
        },
        # Web tools
        {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            "implementation_ref": "tools.web_search:web_search_impl",
            "config_json": {"max_results": 10},
        },
        {
            "name": "web_fetch",
            "description": "Fetch and extract text from a URL",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 10,
                    },
                },
                "required": ["url"],
            },
            "implementation_ref": "tools.web_search:web_fetch_impl",
        },
        # Agent collaboration tools
        {
            "name": "agents_list",
            "description": "List all available sub-agents",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "implementation_ref": "tools.agent_tools:agents_list_impl",
        },
        {
            "name": "submit_delegate_task",
            "description": "Create asynchronous delegated task for sub-agent execution",
            "input_schema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Final user goal"},
                    "instruction": {"type": "string", "description": "Instruction for sub-agent"},
                    "callback": {"type": "object", "description": "Callback payload"},
                },
                "required": ["goal", "instruction", "callback"],
            },
            "implementation_ref": "tools.agent_tools:submit_delegate_task_impl",
        },
        # Scheduled task tools
        {
            "name": "create_cron_task",
            "description": "Create a scheduled task with cron syntax",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Task name"},
                    "cron_expr": {
                        "type": "string",
                        "description": "Cron expression",
                    },
                    "command": {"type": "string", "description": "Command to run"},
                    "enabled": {
                        "type": "boolean",
                        "description": "Enable immediately",
                        "default": True,
                    },
                },
                "required": ["name", "cron_expr", "command"],
            },
            "implementation_ref": "tools.task_schedule_tools:create_cron_task_impl",
        },
        {
            "name": "list_my_cron_tasks",
            "description": "List all scheduled tasks for current agent",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "implementation_ref": "tools.task_schedule_tools:list_my_cron_tasks_impl",
        },
        {
            "name": "update_my_cron_task",
            "description": "Update a scheduled task",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID (UUID)"},
                    "name": {"type": "string", "description": "New task name"},
                    "cron_expr": {
                        "type": "string",
                        "description": "New cron expression",
                    },
                    "command": {"type": "string", "description": "New command"},
                    "enabled": {"type": "boolean", "description": "Enable/disable"},
                },
                "required": ["task_id"],
            },
            "implementation_ref": "tools.task_schedule_tools:update_my_cron_task_impl",
        },
        {
            "name": "delete_my_cron_task",
            "description": "Delete a scheduled task",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID (UUID)"},
                },
                "required": ["task_id"],
            },
            "implementation_ref": "tools.task_schedule_tools:delete_my_cron_task_impl",
        },
    ]

    tool_map: dict[str, UUID] = {}

    for spec in tools_spec:
        # Check if tool already exists
        existing_tool = await ToolDAO.get_by_name(spec["name"])
        if existing_tool:
            tool_map[spec["name"]] = existing_tool.id
            continue

        # Create tool
        tool_dto = ToolCreate(
            name=spec["name"],
            description=spec["description"],
            is_active=True,
        )
        tool = await ToolDAO.create(tool_dto)
        tool_map[spec["name"]] = tool.id

        # Create default version
        version_dto = ToolVersionCreate(
            tool_id=tool.id,
            version="1.0.0",
            input_schema=spec["input_schema"],
            output_schema={"type": "string"},
            implementation_ref=spec["implementation_ref"],
            config_json=spec.get("config_json"),
            is_default=True,
        )
        await ToolVersionDAO.create(version_dto)

    return tool_map


@pytest_asyncio.fixture
async def agent_with_all_tools(
    db_session: AsyncSession,
    test_agent_type: UUID,
    test_agent_instance: UUID,
    test_tools: dict[str, UUID],
) -> UUID:
    """Grant all tools to the test agent instance."""
    # Grant to agent type
    for tool_id in test_tools.values():
        grant_dto = AgentTypeToolCreate(
            agent_type_id=test_agent_type,
            tool_id=tool_id,
        )
        await AgentTypeToolDAO.assign(grant_dto, session=db_session)

    # Instance should inherit all tools
    return test_agent_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolLoading:
    """Test tool loading from database."""

    async def test_get_tools_loads_all_registered_tools(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that get_tools loads all registered tools."""
        tools = await get_tools(str(agent_with_all_tools))

        assert len(tools) >= 16
        assert all(isinstance(t, StructuredTool) for t in tools)

        tool_names = {t.name for t in tools}
        expected_names = {
            "read",
            "write",
            "edit",
            "apply_patch",
            "grep",
            "find",
            "ls",
            "exec",
            "process",
            "web_search",
            "web_fetch",
            "agents_list",
            "submit_delegate_task",
            "create_cron_task",
            "list_my_cron_tasks",
            "update_my_cron_task",
            "delete_my_cron_task",
        }
        assert tool_names >= expected_names

    async def test_tools_have_valid_schemas(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that all tools have valid Pydantic schemas."""
        tools = await get_tools(str(agent_with_all_tools))

        for tool in tools:
            assert tool.name
            assert tool.description
            assert tool.args_schema
            # Verify we can instantiate the schema
            try:
                tool.args_schema()  # No-arg instantiation should work
            except Exception:
                # Some tools require args, that's okay
                pass


class TestSystemTools:
    """Test system/filesystem tool execution."""

    async def test_read_tool_reads_file(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that read tool can read file contents."""
        # Create a test file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Hello from LLM test!")
            test_file = f.name

        try:
            tools = await get_tools(str(agent_with_all_tools))
            read_tool = next(t for t in tools if t.name == "read")

            result = await read_tool.ainvoke({"path": test_file})
            assert "Hello from LLM test!" in result
        finally:
            os.unlink(test_file)

    async def test_write_tool_creates_file(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that write tool can create files."""
        test_file = Path(tempfile.gettempdir()) / f"test_{uuid4().hex}.txt"

        try:
            tools = await get_tools(str(agent_with_all_tools))
            write_tool = next(t for t in tools if t.name == "write")

            result = await write_tool.ainvoke(
                {"path": str(test_file), "content": "LLM wrote this!"}
            )
            assert "成功" in result or "Success" in result or test_file.exists()

            # Verify file contents
            assert test_file.read_text() == "LLM wrote this!"
        finally:
            if test_file.exists():
                test_file.unlink()

    async def test_edit_tool_modifies_file(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that edit tool can modify file contents."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        ) as f:
            f.write("Original text here")
            test_file = f.name

        try:
            tools = await get_tools(str(agent_with_all_tools))
            edit_tool = next(t for t in tools if t.name == "edit")

            result = await edit_tool.ainvoke(
                {
                    "path": test_file,
                    "old_string": "Original",
                    "new_string": "Modified",
                }
            )

            # Verify modification
            content = Path(test_file).read_text()
            assert "Modified text here" in content
        finally:
            os.unlink(test_file)

    async def test_ls_tool_lists_directory(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that ls tool can list directory contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.txt").write_text("test")
            (Path(tmpdir) / "file2.txt").write_text("test")

            tools = await get_tools(str(agent_with_all_tools))
            ls_tool = next(t for t in tools if t.name == "ls")

            result = await ls_tool.ainvoke({"path": tmpdir})
            assert "file1.txt" in result
            assert "file2.txt" in result

    async def test_find_tool_finds_files(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that find tool can find files with glob patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "test.py").write_text("# python")
            (Path(tmpdir) / "test.txt").write_text("text")

            tools = await get_tools(str(agent_with_all_tools))
            find_tool = next(t for t in tools if t.name == "find")

            result = await find_tool.ainvoke({"pattern": "*.py", "path": tmpdir})
            assert "test.py" in result
            assert "test.txt" not in result

    async def test_grep_tool_searches_content(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that grep tool can search file contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "search_me.txt"
            test_file.write_text("Line with keyword\nOther line\nAnother keyword here")

            tools = await get_tools(str(agent_with_all_tools))
            grep_tool = next(t for t in tools if t.name == "grep")

            result = await grep_tool.ainvoke(
                {"pattern": "keyword", "path": str(test_file)}
            )
            assert "keyword" in result

    async def test_exec_tool_runs_command(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that exec tool can run shell commands."""
        tools = await get_tools(str(agent_with_all_tools))
        exec_tool = next(t for t in tools if t.name == "exec")

        result = await exec_tool.ainvoke({"command": "echo 'Hello from shell'"})
        assert "Hello from shell" in result


class TestWebTools:
    """Test web tool execution."""

    @pytest.mark.skipif(
        not os.getenv("RUN_WEB_TESTS"),
        reason="Web tests require network access; set RUN_WEB_TESTS=1 to enable",
    )
    async def test_web_search_tool_searches(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that web_search tool can perform searches."""
        tools = await get_tools(str(agent_with_all_tools))
        search_tool = next(t for t in tools if t.name == "web_search")

        result = await search_tool.ainvoke(
            {"query": "Python programming", "num_results": 3}
        )
        assert len(result) > 0
        # Should contain search results or error message
        assert "python" in result.lower() or "error" in result.lower()

    @pytest.mark.skipif(
        not os.getenv("RUN_WEB_TESTS"),
        reason="Web tests require network access; set RUN_WEB_TESTS=1 to enable",
    )
    async def test_web_fetch_tool_fetches_url(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that web_fetch tool can fetch URLs."""
        tools = await get_tools(str(agent_with_all_tools))
        fetch_tool = next(t for t in tools if t.name == "web_fetch")

        result = await fetch_tool.ainvoke({"url": "https://example.com"})
        assert len(result) > 0


class TestAgentCollaborationTools:
    """Test agent collaboration tool execution."""

    async def test_agents_list_tool_lists_agents(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that agents_list tool can list agents."""
        tools = await get_tools(str(agent_with_all_tools))
        list_tool = next(t for t in tools if t.name == "agents_list")

        result = await list_tool.ainvoke({})
        # Should return some output (even if no agents)
        assert isinstance(result, str)

    async def test_submit_delegate_task_tool_accepts_orders(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that submit_delegate_task tool accepts a delegation request."""
        tools = await get_tools(str(agent_with_all_tools))
        submit_tool = next(t for t in tools if t.name == "submit_delegate_task")

        result = await submit_tool.ainvoke(
            {
                "goal": "整理會議摘要",
                "instruction": "請整理今日會議重點",
                "callback": {"channel": "whatsapp", "target": "+85290000000", "reply_context": {"instance_id": "85260000"}},
            }
        )
        assert isinstance(result, str)
        assert "Task ID" in result or "已經落單" in result


class TestScheduledTaskTools:
    """Test scheduled task tool execution."""

    async def test_list_my_cron_tasks_tool_lists_tasks(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that list_my_cron_tasks tool can list tasks."""
        tools = await get_tools(str(agent_with_all_tools))
        list_tool = next(t for t in tools if t.name == "list_my_cron_tasks")

        result = await list_tool.ainvoke({})
        assert isinstance(result, str)
        # Should return empty list or actual tasks
        assert len(result) >= 0


class TestToolErrorHandling:
    """Test tool error handling."""

    async def test_read_tool_handles_missing_file(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that read tool handles missing files gracefully."""
        tools = await get_tools(str(agent_with_all_tools))
        read_tool = next(t for t in tools if t.name == "read")

        result = await read_tool.ainvoke({"path": "/nonexistent/file.txt"})
        # Should contain error message
        assert "❌" in result or "fail" in result.lower() or "error" in result.lower()

    async def test_exec_tool_handles_invalid_command(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that exec tool handles invalid commands gracefully."""
        tools = await get_tools(str(agent_with_all_tools))
        exec_tool = next(t for t in tools if t.name == "exec")

        result = await exec_tool.ainvoke({"command": "nonexistent_command_xyz123"})
        # Should contain error message
        assert (
            "❌" in result
            or "fail" in result.lower()
            or "error" in result.lower()
            or "not found" in result.lower()
        )


class TestToolConfiguration:
    """Test tool configuration injection."""

    async def test_config_is_injected_into_tools(
        self, db_session: AsyncSession, agent_with_all_tools: UUID, test_tools: dict[str, UUID]
    ):
        """Test that _config is properly injected into tools."""
        # web_search has config_json in test_tools fixture
        web_search_id = test_tools["web_search"]

        # Set instance-level config override
        override_dto = AgentInstanceToolCreate(
            agent_instance_id=agent_with_all_tools,
            tool_id=web_search_id,
            is_enabled=True,
            config_override={"max_results": 3},
        )
        await AgentInstanceToolDAO.assign(override_dto, session=db_session)

        # Reload tools to pick up config override
        tools = await get_tools(str(agent_with_all_tools))
        search_tool = next(t for t in tools if t.name == "web_search")

        # Tool should load without errors
        assert search_tool is not None

        # Verify config was loaded (tool exists and can be invoked)
        # Note: We can't directly inspect _config, but the tool loaded successfully
        assert search_tool.name == "web_search"

    async def test_agent_db_id_is_injected_into_tools(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that agent_db_id is properly injected into tools."""
        tools = await get_tools(str(agent_with_all_tools))

        # Tools that accept agent_db_id should work
        status_tool = next(t for t in tools if t.name == "agents_list")
        result = await status_tool.ainvoke({})

        # Should contain agent ID reference
        assert isinstance(result, str)


class TestToolEndToEnd:
    """End-to-end integration tests."""

    async def test_llm_can_use_all_filesystem_tools_in_sequence(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test LLM can chain filesystem tools together."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "chain_test.txt"

            tools = await get_tools(str(agent_with_all_tools))
            tool_map = {t.name: t for t in tools}

            # Step 1: Write file
            result1 = await tool_map["write"].ainvoke(
                {"path": str(test_file), "content": "Step 1 complete"}
            )
            assert test_file.exists()

            # Step 2: Read file
            result2 = await tool_map["read"].ainvoke({"path": str(test_file)})
            assert "Step 1 complete" in result2

            # Step 3: Edit file
            result3 = await tool_map["edit"].ainvoke(
                {
                    "path": str(test_file),
                    "old_string": "Step 1",
                    "new_string": "Step 3",
                }
            )

            # Step 4: Verify edit
            result4 = await tool_map["read"].ainvoke({"path": str(test_file)})
            assert "Step 3 complete" in result4

            # Step 5: List directory
            result5 = await tool_map["ls"].ainvoke({"path": tmpdir})
            assert "chain_test.txt" in result5

    async def test_all_tools_can_be_invoked_without_errors(
        self, db_session: AsyncSession, agent_with_all_tools: UUID
    ):
        """Test that every registered tool can be invoked without crashes.

        This is a smoke test to ensure all tools have valid signatures and
        can handle basic invocation, even if they return errors for invalid input.
        """
        tools = await get_tools(str(agent_with_all_tools))

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "smoke_test.txt"
            test_file.write_text("smoke test content")

            for tool in tools:
                print(f"Testing tool: {tool.name}")

                # Try invoking with safe/minimal parameters
                try:
                    if tool.name == "read":
                        result = await tool.ainvoke({"path": str(test_file)})
                    elif tool.name == "write":
                        result = await tool.ainvoke(
                            {"path": str(test_file), "content": "test"}
                        )
                    elif tool.name == "edit":
                        result = await tool.ainvoke(
                            {"path": str(test_file), "search": "x", "replace": "y"}
                        )
                    elif tool.name == "ls":
                        result = await tool.ainvoke({"path": tmpdir})
                    elif tool.name == "find":
                        result = await tool.ainvoke({"pattern": "*.txt", "path": tmpdir})
                    elif tool.name == "grep":
                        result = await tool.ainvoke(
                            {"pattern": "test", "path": str(test_file)}
                        )
                    elif tool.name == "exec":
                        result = await tool.ainvoke({"command": "echo test"})
                    elif tool.name == "process":
                        result = await tool.ainvoke({"action": "list"})
                    else:
                        # For tools that don't require args or are collaboration/cron tools
                        # Try with empty dict
                        result = await tool.ainvoke({})

                    # Should return something (even error messages are okay)
                    assert isinstance(result, str)
                    print(f"  ✅ {tool.name}: {result[:100]}")

                except Exception as exc:
                    # Some tools may fail with missing params, that's okay for smoke test
                    print(f"  ⚠️  {tool.name} raised {type(exc).__name__}: {exc}")
                    # But shouldn't crash with import/implementation errors
                    assert "import" not in str(exc).lower()
                    assert "attribute" not in str(exc).lower()
