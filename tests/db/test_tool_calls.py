# pyright: reportMissingImports=false
"""
Tests for tool call database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and JSONB validation for tool_calls table.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine
from db.schema.tool_calls import ToolCall
from db.schema.tasks import Task
from db.schema.tools import Tool, ToolVersion
from db.types import TaskStatus
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation.
    """
    import os
    
    # Use the main database for testing (read from environment)
    dsn = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'agentserver')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'testpass')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'agentserver')}"
    )
    
    engine = create_engine(dsn=dsn)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Create tables for testing
    async with engine.begin() as conn:
        # Create users table (required for FK chain)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create agent_instances table (required for tasks FK)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_instances (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                status TEXT NOT NULL DEFAULT 'idle',
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create tasks table (required for tool_calls FK)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'normal',
                payload JSONB,
                result JSONB,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                session_id TEXT,
                scheduled_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create tools table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tools (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create tool_versions table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tool_versions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                version VARCHAR(50) NOT NULL,
                input_schema JSONB,
                output_schema JSONB,
                implementation_ref TEXT,
                config_json JSONB,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create tool_calls table with FK constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                tool_version_id UUID REFERENCES tool_versions(id) ON DELETE SET NULL,
                input JSONB,
                output JSONB,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                error_message TEXT,
                duration_ms INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
                CHECK (duration_ms >= 0)
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tool_versions_tool_id 
            ON tool_versions(tool_id)
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_versions_default
            ON tool_versions(tool_id)
            WHERE is_default = true
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tool_calls_task 
            ON tool_calls(task_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tool_calls_tool 
            ON tool_calls(tool_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_version_id 
            ON tool_calls(tool_version_id)
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_tool_calls_tool_version_id"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_tool_calls_tool"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_tool_calls_task"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_tool_versions_default"))
        await conn.execute(text("DROP TABLE IF EXISTS tool_calls"))
        await conn.execute(text("DROP TABLE IF EXISTS tool_versions"))
        await conn.execute(text("DROP TABLE IF EXISTS tools"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> UUID:
    """Create a sample user for testing."""
    from sqlalchemy import text
    
    result = await db_session.execute(text("""
        INSERT INTO users (username, email) 
        VALUES ('testuser_toolcalls', 'test@example.com')
        RETURNING id
    """))
    await db_session.commit()
    return result.scalar_one()


@pytest_asyncio.fixture
async def sample_task(db_session: AsyncSession, sample_user: UUID) -> UUID:
    """Create a sample task for testing."""
    from sqlalchemy import text
    
    result = await db_session.execute(text("""
        INSERT INTO tasks (user_id, task_type, status) 
        VALUES (:user_id, 'test_task', 'pending')
        RETURNING id
    """), {"user_id": sample_user})
    await db_session.commit()
    return result.scalar_one()


@pytest_asyncio.fixture
async def sample_tool(db_session: AsyncSession) -> UUID:
    """Create a sample tool for testing."""
    from sqlalchemy import text
    
    result = await db_session.execute(text("""
        INSERT INTO tools (name, description) 
        VALUES ('TestTool', 'A test tool for tool_calls testing')
        RETURNING id
    """))
    await db_session.commit()
    return result.scalar_one()


@pytest_asyncio.fixture
async def sample_tool_version(db_session: AsyncSession, sample_tool: UUID) -> UUID:
    """Create a sample tool version for testing."""
    from sqlalchemy import text
    
    result = await db_session.execute(text("""
        INSERT INTO tool_versions (tool_id, version, is_default) 
        VALUES (:tool_id, '1.0.0', true)
        RETURNING id
    """), {"tool_id": sample_tool})
    await db_session.commit()
    return result.scalar_one()


class TestToolCallSchema:
    """Test tool_calls schema creation and structure."""
    
    async def test_tool_calls_table_exists(self, db_session: AsyncSession):
        """Test that the tool_calls table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'tool_calls'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "tool_calls"
    
    async def test_tool_calls_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in tool_calls table."""
        expected_columns = {
            'id', 'task_id', 'tool_id', 'tool_version_id', 'input', 'output',
            'status', 'error_message', 'duration_ms', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'tool_calls'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_tool_calls_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'tool_calls'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_tool_calls_task' in indexes
        assert 'idx_tool_calls_tool' in indexes
        assert 'idx_tool_calls_tool_version_id' in indexes
    
    async def test_check_constraints_exist(self, db_session: AsyncSession):
        """Test that CHECK constraints exist for status and duration_ms."""
        result = await db_session.execute(
            text("""
                SELECT conname 
                FROM pg_constraint 
                WHERE conrelid = 'tool_calls'::regclass 
                AND contype = 'c'
            """)
        )
        constraints = {row[0] for row in result.fetchall()}
        
        assert 'ck_tool_calls_status' in constraints
        assert 'ck_tool_calls_duration_ms' in constraints


class TestToolCallCRUD:
    """Test CRUD operations for ToolCall model."""
    
    async def test_create_tool_call_minimal(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test creating a tool call with minimal fields."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.id is not None
        assert isinstance(tool_call.id, UUID)
        assert tool_call.task_id == sample_task
        assert tool_call.tool_id == sample_tool
        assert tool_call.tool_version_id is None
        assert tool_call.input is None
        assert tool_call.output is None
        assert tool_call.status == "pending"
        assert tool_call.error_message is None
        assert tool_call.duration_ms is None
        assert tool_call.created_at is not None
        assert tool_call.updated_at is not None
    
    async def test_create_tool_call_full(
        self, db_session: AsyncSession, sample_task: UUID, 
        sample_tool: UUID, sample_tool_version: UUID
    ):
        """Test creating a tool call with all fields."""
        input_data = {"query": "test query", "limit": 10}
        output_data = {"results": ["result1", "result2"], "count": 2}
        
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            tool_version_id=sample_tool_version,
            input=input_data,
            output=output_data,
            status="completed",
            error_message=None,
            duration_ms=150,
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.task_id == sample_task
        assert tool_call.tool_id == sample_tool
        assert tool_call.tool_version_id == sample_tool_version
        assert tool_call.input == input_data
        assert tool_call.output == output_data
        assert tool_call.status == "completed"
        assert tool_call.duration_ms == 150
        assert isinstance(tool_call.input, dict)
        assert tool_call.input["query"] == "test query"
        assert isinstance(tool_call.output, dict)
        assert tool_call.output["count"] == 2
    
    async def test_update_tool_call(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test updating a tool call."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            status="pending",
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        original_updated_at = tool_call.updated_at
        await asyncio.sleep(0.01)  # Ensure time difference
        
        tool_call.status = "running"
        tool_call.input = {"query": "updated query"}
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.status == "running"
        assert tool_call.input == {"query": "updated query"}
        assert tool_call.updated_at > original_updated_at
    
    async def test_update_tool_call_to_completed(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test updating a tool call to completed with output and duration."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            status="running",
            input={"query": "test"},
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        tool_call.status = "completed"
        tool_call.output = {"results": ["success"]}
        tool_call.duration_ms = 200
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.status == "completed"
        assert tool_call.output == {"results": ["success"]}
        assert tool_call.duration_ms == 200
    
    async def test_update_tool_call_to_failed(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test updating a tool call to failed with error message."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            status="running",
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        tool_call.status = "failed"
        tool_call.error_message = "Connection timeout after 30s"
        tool_call.duration_ms = 30000
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.status == "failed"
        assert tool_call.error_message == "Connection timeout after 30s"
        assert tool_call.duration_ms == 30000
    
    async def test_delete_tool_call(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test deleting a tool call."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        await db_session.delete(tool_call)
        await db_session.commit()
        
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tool_call.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_get_tool_call_by_id(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test retrieving a tool call by ID."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            status="completed",
            input={"param": "value"},
            output={"result": "success"},
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tool_call.id)
        )
        retrieved = result.scalar_one()
        
        assert retrieved.task_id == sample_task
        assert retrieved.tool_id == sample_tool
        assert retrieved.status == "completed"
    
    async def test_list_tool_calls_by_task(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test filtering tool calls by task_id."""
        # Create multiple tool calls for the same task
        tool_call1 = ToolCall(task_id=sample_task, tool_id=sample_tool, status="completed")
        tool_call2 = ToolCall(task_id=sample_task, tool_id=sample_tool, status="completed")
        db_session.add_all([tool_call1, tool_call2])
        await db_session.commit()
        
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.task_id == sample_task)
        )
        tool_calls = result.scalars().all()
        
        assert len(tool_calls) == 2
        assert all(tc.task_id == sample_task for tc in tool_calls)
    
    async def test_list_tool_calls_by_tool(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test filtering tool calls by tool_id."""
        # Create multiple tool calls for the same tool
        tool_call1 = ToolCall(task_id=sample_task, tool_id=sample_tool, status="pending")
        tool_call2 = ToolCall(task_id=sample_task, tool_id=sample_tool, status="running")
        db_session.add_all([tool_call1, tool_call2])
        await db_session.commit()
        
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.tool_id == sample_tool)
        )
        tool_calls = result.scalars().all()
        
        assert len(tool_calls) == 2
        assert all(tc.tool_id == sample_tool for tc in tool_calls)
    
    async def test_filter_tool_calls_by_status(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test filtering tool calls by status."""
        # Create tool calls with different statuses
        pending_call = ToolCall(task_id=sample_task, tool_id=sample_tool, status="pending")
        running_call = ToolCall(task_id=sample_task, tool_id=sample_tool, status="running")
        completed_call = ToolCall(task_id=sample_task, tool_id=sample_tool, status="completed")
        failed_call = ToolCall(task_id=sample_task, tool_id=sample_tool, status="failed")
        db_session.add_all([pending_call, running_call, completed_call, failed_call])
        await db_session.commit()
        
        # Query by status
        for status in ["pending", "running", "completed", "failed"]:
            result = await db_session.execute(
                select(ToolCall).where(ToolCall.status == status)
            )
            calls = result.scalars().all()
            assert len(calls) == 1
            assert calls[0].status == status


class TestToolCallForeignKeyConstraints:
    """Test foreign key constraints for tool_calls."""
    
    async def test_cascade_delete_on_task_delete(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that deleting a task cascades to delete its tool calls."""
        # Create tool call
        tool_call = ToolCall(task_id=sample_task, tool_id=sample_tool)
        db_session.add(tool_call)
        await db_session.commit()
        
        tool_call_id = tool_call.id
        
        # Delete task using raw SQL (CASCADE should delete tool_calls)
        await db_session.execute(text(f"DELETE FROM tasks WHERE id = '{sample_task}'"))
        await db_session.commit()
        
        # Verify tool call is also deleted (CASCADE)
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tool_call_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_cascade_delete_on_tool_delete(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that deleting a tool cascades to delete its tool calls."""
        # Create tool call
        tool_call = ToolCall(task_id=sample_task, tool_id=sample_tool)
        db_session.add(tool_call)
        await db_session.commit()
        
        tool_call_id = tool_call.id
        
        # Delete tool using raw SQL (CASCADE should delete tool_calls)
        await db_session.execute(text(f"DELETE FROM tools WHERE id = '{sample_tool}'"))
        await db_session.commit()
        
        # Verify tool call is also deleted (CASCADE)
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tool_call_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_set_null_on_tool_version_delete(
        self, db_session: AsyncSession, sample_task: UUID, 
        sample_tool: UUID, sample_tool_version: UUID
    ):
        """Test that deleting a tool version sets tool_version_id to NULL."""
        # Create tool call with version
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            tool_version_id=sample_tool_version,
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        tool_call_id = tool_call.id
        
        # Delete tool version using raw SQL (SET NULL should preserve tool_call)
        await db_session.execute(
            text(f"DELETE FROM tool_versions WHERE id = '{sample_tool_version}'")
        )
        await db_session.commit()
        
        # Verify tool call still exists but tool_version_id is NULL
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tool_call_id)
        )
        remaining_call = result.scalar_one()
        assert remaining_call is not None
        assert remaining_call.tool_version_id is None
    
    async def test_cannot_create_tool_call_without_task(
        self, db_session: AsyncSession, sample_tool: UUID
    ):
        """Test that creating a tool call with invalid task_id fails."""
        fake_task_id = uuid4()
        
        tool_call = ToolCall(task_id=fake_task_id, tool_id=sample_tool)
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cannot_create_tool_call_without_tool(
        self, db_session: AsyncSession, sample_task: UUID
    ):
        """Test that creating a tool call with invalid tool_id fails."""
        fake_tool_id = uuid4()
        
        tool_call = ToolCall(task_id=sample_task, tool_id=fake_tool_id)
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_create_tool_call_without_tool_version(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that creating a tool call without tool_version_id succeeds."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            tool_version_id=None,
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        assert tool_call.id is not None
        assert tool_call.tool_version_id is None


class TestToolCallCheckConstraints:
    """Test CHECK constraints for tool_calls."""
    
    async def test_invalid_status_rejected(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that invalid status values are rejected."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            status="invalid_status",
        )
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_valid_statuses_accepted(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that all valid status values are accepted."""
        valid_statuses = ["pending", "running", "completed", "failed"]
        
        for status in valid_statuses:
            tool_call = ToolCall(
                task_id=sample_task,
                tool_id=sample_tool,
                status=status,
            )
            db_session.add(tool_call)
            await db_session.commit()
            await db_session.refresh(tool_call)
            assert tool_call.status == status
            # Clean up
            await db_session.delete(tool_call)
            await db_session.commit()
    
    async def test_negative_duration_rejected(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that negative duration_ms is rejected."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            duration_ms=-100,
        )
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_zero_duration_accepted(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that zero duration_ms is accepted."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            duration_ms=0,
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        assert tool_call.duration_ms == 0
    
    async def test_positive_duration_accepted(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test that positive duration_ms is accepted."""
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            duration_ms=5000,
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        assert tool_call.duration_ms == 5000


class TestToolCallPydanticModels:
    """Test Pydantic model validation."""
    
    def test_tool_call_create_validation(self):
        """Test ToolCallCreate model validation."""
        from db.models.tool_call import ToolCallCreate
        
        task_id = uuid4()
        tool_id = uuid4()
        
        tool_call_data = {
            "task_id": task_id,
            "tool_id": tool_id,
            "input": {"query": "test"},
            "output": {"result": "success"},
            "status": "completed",
            "duration_ms": 100,
        }
        tool_call = ToolCallCreate(**tool_call_data)
        assert tool_call.task_id == task_id
        assert tool_call.tool_id == tool_id
        assert tool_call.input == {"query": "test"}
        assert tool_call.output == {"result": "success"}
        assert tool_call.status == "completed"
        assert tool_call.duration_ms == 100
    
    def test_tool_call_update_validation(self):
        """Test ToolCallUpdate model validation."""
        from db.models.tool_call import ToolCallUpdate
        
        update_data = {
            "status": "completed",
            "output": {"results": ["result1"]},
            "duration_ms": 250,
        }
        update = ToolCallUpdate(**update_data)
        assert update.status == "completed"
        assert update.output == {"results": ["result1"]}
        assert update.duration_ms == 250
    
    def test_tool_call_model_from_attributes(self):
        """Test ToolCall model with from_attributes."""
        from db.models.tool_call import ToolCall
        
        tool_call = ToolCall.model_validate(
            {
                "id": str(uuid4()),
                "task_id": str(uuid4()),
                "tool_id": str(uuid4()),
                "tool_version_id": None,
                "input": {"query": "test"},
                "output": {"result": "success"},
                "status": "completed",
                "error_message": None,
                "duration_ms": 100,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
            from_attributes=True,
        )
        assert tool_call.status == "completed"
        assert tool_call.duration_ms == 100
        assert tool_call.input is not None
        assert tool_call.input["query"] == "test"
    
    def test_tool_call_negative_duration_rejected(self):
        """Test that negative duration_ms is rejected by Pydantic."""
        from db.models.tool_call import ToolCallUpdate
        
        with pytest.raises(Exception):  # pydantic.ValidationError
            ToolCallUpdate(duration_ms=-100)


class TestToolCallJSONBValidation:
    """Test JSONB field validation."""
    
    async def test_complex_nested_input(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test tool call with complex nested input JSON."""
        complex_input = {
            "query": "test",
            "filters": {
                "date_range": {"start": "2026-01-01", "end": "2026-12-31"},
                "categories": ["cat1", "cat2"],
            },
            "options": {
                "limit": 100,
                "offset": 0,
                "sort": {"field": "created_at", "order": "desc"},
            },
        }
        
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            input=complex_input,
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.input == complex_input
        assert tool_call.input["filters"]["date_range"]["start"] == "2026-01-01"
        assert len(tool_call.input["options"]["categories"]) == 2
    
    async def test_complex_nested_output(
        self, db_session: AsyncSession, sample_task: UUID, sample_tool: UUID
    ):
        """Test tool call with complex nested output JSON."""
        complex_output = {
            "results": [
                {"id": 1, "name": "item1", "metadata": {"score": 0.95}},
                {"id": 2, "name": "item2", "metadata": {"score": 0.87}},
            ],
            "total": 2,
            "pagination": {"page": 1, "per_page": 10, "total_pages": 1},
        }
        
        tool_call = ToolCall(
            task_id=sample_task,
            tool_id=sample_tool,
            output=complex_output,
            status="completed",
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        assert tool_call.output == complex_output
        assert len(tool_call.output["results"]) == 2
        assert tool_call.output["results"][0]["metadata"]["score"] == 0.95
