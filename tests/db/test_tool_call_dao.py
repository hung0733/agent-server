# pyright: reportMissingImports=false
"""
Tests for ToolCallDAO database operations.

This module tests CRUD operations for ToolCallDAO following the DAO pattern.

Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.tool_call_dto import ToolCallCreate, ToolCall, ToolCallUpdate
from db.dto.tool_dto import ToolCreate, Tool, ToolVersionCreate, ToolVersion
from db.dto.task_dto import TaskCreate, Task
from db.dao.tool_call_dao import ToolCallDAO
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from db.dao.task_dao import TaskDAO
from db.entity.tool_call_entity import ToolCall as ToolCallEntity
from db.entity.tool_entity import Tool as ToolEntity, ToolVersion as ToolVersionEntity
from db.entity.task_entity import Task as TaskEntity
from db.entity.user_entity import User as UserEntity
from db.entity.llm_endpoint_entity import LLMEndpoint, LLMEndpointGroup  # Required for UserEntity relationships


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation by cleaning data rather than dropping tables.
    """
    dsn = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'agentserver')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'testpass')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'agentserver')}"
    )
    
    engine = create_engine(dsn=dsn)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        yield session
        await session.rollback()
    
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_data(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean all tool call-related tables before and after tests."""
    # Clean before test
    await db_session.execute(delete(ToolCallEntity))
    await db_session.execute(delete(ToolVersionEntity))
    await db_session.execute(delete(ToolEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    # Clean after test
    await db_session.rollback()
    await db_session.execute(delete(ToolCallEntity))
    await db_session.execute(delete(ToolVersionEntity))
    await db_session.execute(delete(ToolEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, clean_data: None) -> UserEntity:
    """Create a test user for task ownership."""
    user = UserEntity(
        username="toolcalltestuser",
        email="toolcalltest@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_task(db_session: AsyncSession, test_user: UserEntity) -> Task:
    """Create a test task for tool call association."""
    task_create = TaskCreate(
        user_id=test_user.id,
        task_type="research",
    )
    return await TaskDAO.create(task_create, session=db_session)


@pytest_asyncio.fixture
async def test_tool(db_session: AsyncSession) -> Tool:
    """Create a test tool for tool call association."""
    tool_create = ToolCreate(
        name="test_web_search",
        description="Test tool for searching the web",
        is_active=True,
    )
    return await ToolDAO.create(tool_create, session=db_session)


@pytest_asyncio.fixture
async def test_tool_version(db_session: AsyncSession, test_tool: Tool) -> ToolVersion:
    """Create a test tool version for tool call association."""
    version_create = ToolVersionCreate(
        tool_id=test_tool.id,
        version="1.0.0",
        is_default=True,
    )
    return await ToolVersionDAO.create(version_create, session=db_session)


# =============================================================================
# ToolCall DAO CRUD Tests
# =============================================================================

class TestToolCallDAOCreate:
    """Test create operations for ToolCallDAO."""
    
    async def test_create_tool_call_with_minimal_fields(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test creating a tool call with only required fields."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        assert created_call is not None
        assert created_call.id is not None
        assert isinstance(created_call.id, UUID)
        assert created_call.task_id == test_task.id
        assert created_call.tool_id == test_tool.id
        assert created_call.tool_version_id is None
        assert created_call.status == "pending"  # Default value
        assert created_call.input is None
        assert created_call.output is None
        assert created_call.error_message is None
        assert created_call.duration_ms is None
        assert created_call.created_at is not None
        assert created_call.updated_at is not None
        assert isinstance(created_call.created_at, datetime)
        assert isinstance(created_call.updated_at, datetime)
    
    async def test_create_tool_call_with_all_fields(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool, test_tool_version: ToolVersion
    ):
        """Test creating a tool call with all fields specified."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
            tool_version_id=test_tool_version.id,
            input={"query": "test query", "max_results": 5},
            output={"results": ["result1", "result2"]},
            status="completed",
            error_message=None,
            duration_ms=1500,
        )
        
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        assert created_call is not None
        assert created_call.task_id == test_task.id
        assert created_call.tool_id == test_tool.id
        assert created_call.tool_version_id == test_tool_version.id
        assert created_call.input == {"query": "test query", "max_results": 5}
        assert created_call.output == {"results": ["result1", "result2"]}
        assert created_call.status == "completed"
        assert created_call.duration_ms == 1500
    
    async def test_create_tool_call_with_running_status(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test creating a tool call with running status."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
            status="running",
        )
        
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        assert created_call.status == "running"
    
    async def test_create_tool_call_with_failed_status(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test creating a tool call with failed status and error message."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
            status="failed",
            error_message="Connection timeout after 30 seconds",
        )
        
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        assert created_call.status == "failed"
        assert created_call.error_message == "Connection timeout after 30 seconds"
    
    async def test_create_tool_call_returns_dto(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that create returns a ToolCall DTO, not an entity."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        assert isinstance(created_call, ToolCall)


class TestToolCallDAOGetById:
    """Test get_by_id operations for ToolCallDAO."""
    
    async def test_get_by_id_returns_tool_call(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test retrieving a tool call by ID."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        fetched_call = await ToolCallDAO.get_by_id(created_call.id, session=db_session)
        
        assert fetched_call is not None
        assert fetched_call.id == created_call.id
        assert fetched_call.task_id == test_task.id
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        nonexistent_id = uuid4()
        
        result = await ToolCallDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that get_by_id returns a ToolCall DTO."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        fetched_call = await ToolCallDAO.get_by_id(created_call.id, session=db_session)
        
        assert isinstance(fetched_call, ToolCall)


class TestToolCallDAOGetByTaskId:
    """Test get_by_task_id operations for ToolCallDAO."""
    
    async def test_get_by_task_id_returns_tool_calls(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test retrieving tool calls by task ID."""
        for i in range(3):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
                input={"iteration": i},
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        calls = await ToolCallDAO.get_by_task_id(test_task.id, session=db_session)
        
        assert len(calls) == 3
    
    async def test_get_by_task_id_empty_returns_empty_list(
        self, db_session: AsyncSession, test_task: Task
    ):
        """Test that get_by_task_id returns empty list when no tool calls."""
        calls = await ToolCallDAO.get_by_task_id(test_task.id, session=db_session)
        
        assert calls == []


class TestToolCallDAOGetByToolId:
    """Test get_by_tool_id operations for ToolCallDAO."""
    
    async def test_get_by_tool_id_returns_tool_calls(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test retrieving tool calls by tool ID."""
        for i in range(3):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
                input={"iteration": i},
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        calls = await ToolCallDAO.get_by_tool_id(test_tool.id, session=db_session)
        
        assert len(calls) == 3
    
    async def test_get_by_tool_id_empty_returns_empty_list(
        self, db_session: AsyncSession, test_tool: Tool
    ):
        """Test that get_by_tool_id returns empty list when no tool calls."""
        calls = await ToolCallDAO.get_by_tool_id(test_tool.id, session=db_session)
        
        assert calls == []


class TestToolCallDAOGetAll:
    """Test get_all operations for ToolCallDAO."""
    
    async def test_get_all_returns_all_tool_calls(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test retrieving all tool calls."""
        for i in range(3):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        calls = await ToolCallDAO.get_all(session=db_session)
        
        assert len(calls) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_all returns empty list when no tool calls exist."""
        calls = await ToolCallDAO.get_all(session=db_session)
        
        assert calls == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        # Test limit
        calls_limited = await ToolCallDAO.get_all(limit=2, session=db_session)
        assert len(calls_limited) == 2
        
        # Test offset
        calls_offset = await ToolCallDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(calls_offset) == 2
    
    async def test_get_all_with_status_filter(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test get_all with status filter."""
        # Create tool calls with different statuses
        call1 = ToolCallCreate(task_id=test_task.id, tool_id=test_tool.id, status="pending")
        call2 = ToolCallCreate(task_id=test_task.id, tool_id=test_tool.id, status="running")
        call3 = ToolCallCreate(task_id=test_task.id, tool_id=test_tool.id, status="completed")
        
        await ToolCallDAO.create(call1, session=db_session)
        await ToolCallDAO.create(call2, session=db_session)
        await ToolCallDAO.create(call3, session=db_session)
        
        # Filter by pending status
        pending_calls = await ToolCallDAO.get_all(status="pending", session=db_session)
        assert len(pending_calls) == 1
        assert pending_calls[0].status == "pending"
        
        # Filter by completed status
        completed_calls = await ToolCallDAO.get_all(status="completed", session=db_session)
        assert len(completed_calls) == 1
        assert completed_calls[0].status == "completed"


class TestToolCallDAOUpdate:
    """Test update operations for ToolCallDAO."""
    
    async def test_update_tool_call_status(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test updating a tool call's status."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        tool_call_update = ToolCallUpdate(
            id=created_call.id,
            status="running",
        )
        updated_call = await ToolCallDAO.update(tool_call_update, session=db_session)
        
        assert updated_call is not None
        assert updated_call.status == "running"
        assert updated_call.updated_at >= created_call.updated_at
    
    async def test_update_tool_call_output(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test updating a tool call's output."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        tool_call_update = ToolCallUpdate(
            id=created_call.id,
            status="completed",
            output={"results": ["result1", "result2"], "count": 2},
            duration_ms=1500,
        )
        updated_call = await ToolCallDAO.update(tool_call_update, session=db_session)
        
        assert updated_call is not None
        assert updated_call.output == {"results": ["result1", "result2"], "count": 2}
        assert updated_call.status == "completed"
        assert updated_call.duration_ms == 1500
    
    async def test_update_tool_call_error(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test updating a tool call with error information."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        tool_call_update = ToolCallUpdate(
            id=created_call.id,
            status="failed",
            error_message="Connection timeout after 30 seconds",
        )
        updated_call = await ToolCallDAO.update(tool_call_update, session=db_session)
        
        assert updated_call is not None
        assert updated_call.status == "failed"
        assert updated_call.error_message == "Connection timeout after 30 seconds"
    
    async def test_update_nonexistent_tool_call_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that updating a nonexistent tool call returns None."""
        from uuid import uuid4
        
        tool_call_update = ToolCallUpdate(
            id=uuid4(),
            status="running",
        )
        
        result = await ToolCallDAO.update(tool_call_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that update returns a ToolCall DTO."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        tool_call_update = ToolCallUpdate(
            id=created_call.id,
            status="completed",
        )
        updated_call = await ToolCallDAO.update(tool_call_update, session=db_session)
        
        assert isinstance(updated_call, ToolCall)


class TestToolCallDAODelete:
    """Test delete operations for ToolCallDAO."""
    
    async def test_delete_existing_tool_call(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test deleting an existing tool call."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        result = await ToolCallDAO.delete(created_call.id, session=db_session)
        
        assert result is True
        
        # Verify tool call is deleted
        fetched = await ToolCallDAO.get_by_id(created_call.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_tool_call_returns_false(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that deleting a nonexistent tool call returns False."""
        from uuid import uuid4
        
        result = await ToolCallDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestToolCallDAOExists:
    """Test exists operations for ToolCallDAO."""
    
    async def test_exists_returns_true_for_existing_tool_call(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that exists returns True for existing tool call."""
        tool_call_create = ToolCallCreate(
            task_id=test_task.id,
            tool_id=test_tool.id,
        )
        created_call = await ToolCallDAO.create(tool_call_create, session=db_session)
        
        result = await ToolCallDAO.exists(created_call.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_tool_call(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that exists returns False for nonexistent tool call."""
        from uuid import uuid4
        
        result = await ToolCallDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestToolCallDAOCount:
    """Test count operations for ToolCallDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that count returns the correct number of tool calls."""
        for i in range(3):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        count = await ToolCallDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that count returns 0 for empty table."""
        count = await ToolCallDAO.count(session=db_session)
        
        assert count == 0


class TestToolCallDAOCountByTask:
    """Test count_by_task operations for ToolCallDAO."""
    
    async def test_count_by_task_returns_correct_number(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that count_by_task returns the correct number of tool calls for a task."""
        for i in range(3):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        count = await ToolCallDAO.count_by_task(test_task.id, session=db_session)
        
        assert count == 3
    
    async def test_count_by_task_empty_returns_zero(
        self, db_session: AsyncSession, test_task: Task
    ):
        """Test that count_by_task returns 0 when no tool calls for the task."""
        count = await ToolCallDAO.count_by_task(test_task.id, session=db_session)
        
        assert count == 0


class TestToolCallDAOCountByTool:
    """Test count_by_tool operations for ToolCallDAO."""
    
    async def test_count_by_tool_returns_correct_number(
        self, db_session: AsyncSession, test_task: Task, test_tool: Tool
    ):
        """Test that count_by_tool returns the correct number of tool calls for a tool."""
        for i in range(3):
            tool_call_create = ToolCallCreate(
                task_id=test_task.id,
                tool_id=test_tool.id,
            )
            await ToolCallDAO.create(tool_call_create, session=db_session)
        
        count = await ToolCallDAO.count_by_tool(test_tool.id, session=db_session)
        
        assert count == 3
    
    async def test_count_by_tool_empty_returns_zero(
        self, db_session: AsyncSession, test_tool: Tool
    ):
        """Test that count_by_tool returns 0 when no tool calls for the tool."""
        count = await ToolCallDAO.count_by_tool(test_tool.id, session=db_session)
        
        assert count == 0