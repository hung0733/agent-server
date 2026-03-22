# pyright: reportMissingImports=false
"""
Tests for task database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and JSONB validation for tasks table.
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

from db import create_engine, AsyncSession
from db.schema.tasks import Task
from db.schema.llm_endpoints import LLMEndpointGroup  # noqa: F401 - Import for relationship resolution
from db.types import TaskStatus, Priority, gen_random_uuid


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation.
    """
    import os
    
    # Use the main database for testing
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
        # Create users table first (FK dependency)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create agent_types table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_types (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                capabilities JSONB,
                default_config JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create agent_instances table with FK constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_instances (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_type_id UUID NOT NULL REFERENCES agent_types(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT,
                status TEXT NOT NULL DEFAULT 'idle' 
                    CHECK (status IN ('idle', 'busy', 'error', 'offline')),
                config JSONB,
                last_heartbeat_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create tasks table with all constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                session_id TEXT,
                parent_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'critical')),
                payload JSONB,
                result JSONB,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                scheduled_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_id, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id)
        """))
        # Partial index for scheduled tasks
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_pending
            ON tasks(scheduled_at)
            WHERE status = 'pending'
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestTaskSchema:
    """Test tasks schema creation and structure."""
    
    async def test_tasks_table_exists(self, db_session: AsyncSession):
        """Test that the tasks table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'tasks'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "tasks"
    
    async def test_tasks_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in tasks table."""
        expected_columns = {
            'id', 'user_id', 'agent_id', 'session_id', 'parent_task_id',
            'task_type', 'status', 'priority', 'payload', 'result',
            'error_message', 'retry_count', 'max_retries', 'scheduled_at',
            'started_at', 'completed_at', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'tasks'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_tasks_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'tasks'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_tasks_status' in indexes
        assert 'idx_tasks_user' in indexes
        assert 'idx_tasks_agent' in indexes
        assert 'idx_tasks_parent_task_id' in indexes
        assert 'idx_tasks_scheduled_pending' in indexes


class TestTaskCRUD:
    """Test CRUD operations for Task model."""
    
    async def test_create_task_minimal(self, db_session: AsyncSession):
        """Test creating a task with minimal fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        task = Task(
            user_id=user_id,
            task_type="research",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.id is not None
        assert isinstance(task.id, UUID)
        assert task.user_id == user_id
        assert task.task_type == "research"
        assert task.status == TaskStatus.pending
        assert task.priority == Priority.normal
        assert task.payload is None
        assert task.result is None
        assert task.error_message is None
        assert task.retry_count == 0
        assert task.max_retries == 3
    
    async def test_create_task_full(self, db_session: AsyncSession):
        """Test creating a task with all fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        
        agent_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status) 
            VALUES ('{agent_id}', '{agent_type_id}', '{user_id}', 'idle')
        """))
        await db_session.commit()
        
        payload = {
            "query": "latest AI developments",
            "max_results": 5,
            "sources": ["arxiv", "github"],
        }
        
        scheduled_time = datetime.now(timezone.utc)
        
        task = Task(
            user_id=user_id,
            agent_id=agent_id,
            session_id="thread-abc123",
            task_type="research",
            status=TaskStatus.pending,
            priority=Priority.high,
            payload=payload,
            max_retries=5,
            scheduled_at=scheduled_time,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.agent_id == agent_id
        assert task.session_id == "thread-abc123"
        assert task.task_type == "research"
        assert task.status == TaskStatus.pending
        assert task.priority == Priority.high
        assert isinstance(task.payload, dict)
        assert task.payload["query"] == "latest AI developments"
        assert task.payload["max_results"] == 5
        assert task.max_retries == 5
        assert task.scheduled_at is not None
    
    async def test_update_task_status(self, db_session: AsyncSession):
        """Test updating task status through lifecycle."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        task = Task(
            user_id=user_id,
            task_type="analysis",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        
        original_updated_at = task.updated_at
        await asyncio.sleep(0.01)
        
        # Transition to running
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.status == TaskStatus.running
        assert task.started_at is not None
        assert task.updated_at > original_updated_at
        
        # Transition to completed
        original_updated_at = task.updated_at
        await asyncio.sleep(0.01)
        
        task.status = TaskStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        task.result = {"findings": ["finding1", "finding2"]}
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.status == TaskStatus.completed
        assert task.completed_at is not None
        assert task.result is not None
    
    async def test_task_with_error_and_retry(self, db_session: AsyncSession):
        """Test task error handling and retry count."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        task = Task(
            user_id=user_id,
            task_type="code_generation",
            status=TaskStatus.running,
            retry_count=0,
            max_retries=3,
        )
        db_session.add(task)
        await db_session.commit()
        
        # Simulate failure
        task.status = TaskStatus.failed
        task.error_message = "Connection timeout"
        task.retry_count = 1
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.status == TaskStatus.failed
        assert task.error_message == "Connection timeout"
        assert task.retry_count == 1
    
    async def test_delete_task(self, db_session: AsyncSession):
        """Test deleting a task."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        task = Task(user_id=user_id, task_type="test")
        db_session.add(task)
        await db_session.commit()
        
        await db_session.delete(task)
        await db_session.commit()
        
        result = await db_session.execute(
            select(Task).where(Task.id == task.id)
        )
        assert result.scalar_one_or_none() is None


class TestParentChildTasks:
    """Test parent-child task relationships."""
    
    async def test_create_parent_child_tasks(self, db_session: AsyncSession):
        """Test creating parent and child tasks."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create parent task
        parent = Task(
            user_id=user_id,
            task_type="research",
            status=TaskStatus.pending,
        )
        db_session.add(parent)
        await db_session.commit()
        await db_session.refresh(parent)
        
        # Create child task
        child = Task(
            user_id=user_id,
            parent_task_id=parent.id,
            task_type="web_search",
            status=TaskStatus.pending,
        )
        db_session.add(child)
        await db_session.commit()
        await db_session.refresh(child)
        
        assert child.parent_task_id == parent.id
        
        # Verify parent-child relationship via query instead of lazy loading
        result = await db_session.execute(
            select(Task).where(Task.parent_task_id == parent.id)
        )
        children = result.scalars().all()
        assert len(children) == 1
        assert children[0].id == child.id
    
    async def test_cascade_delete_parent_task(self, db_session: AsyncSession):
        """Test that deleting parent task cascades to children."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create parent
        parent = Task(user_id=user_id, task_type="parent")
        db_session.add(parent)
        await db_session.commit()
        
        # Create children
        for i in range(3):
            child = Task(
                user_id=user_id,
                parent_task_id=parent.id,
                task_type=f"child_{i}",
            )
            db_session.add(child)
        await db_session.commit()
        
        # Delete parent
        await db_session.delete(parent)
        await db_session.commit()
        
        # Verify children are deleted
        result = await db_session.execute(
            select(Task).where(Task.parent_task_id == parent.id)
        )
        children = result.scalars().all()
        assert len(children) == 0


class TestForeignKeys:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_user_id_enforced(self, db_session: AsyncSession):
        """Test that user_id FK constraint is enforced."""
        fake_user_id = uuid4()
        
        task = Task(
            user_id=fake_user_id,
            task_type="test",
        )
        db_session.add(task)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_fk_agent_id_set_null(self, db_session: AsyncSession):
        """Test that agent_id FK sets NULL on agent deletion."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        
        agent_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status) 
            VALUES ('{agent_id}', '{agent_type_id}', '{user_id}', 'idle')
        """))
        await db_session.commit()
        
        # Create task with agent
        task = Task(
            user_id=user_id,
            agent_id=agent_id,
            task_type="test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.agent_id == agent_id
        
        # Delete agent
        await db_session.execute(text(f"""
            DELETE FROM agent_instances WHERE id = '{agent_id}'
        """))
        await db_session.commit()
        
        # Verify task still exists but agent_id is NULL
        await db_session.refresh(task)
        assert task.agent_id is None
    
    async def test_cascade_delete_user(self, db_session: AsyncSession):
        """Test that deleting user cascades to tasks."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create tasks for this user
        for i in range(3):
            task = Task(
                user_id=user_id,
                task_type=f"task_{i}",
            )
            db_session.add(task)
        await db_session.commit()
        
        # Delete user
        await db_session.execute(text(f"""
            DELETE FROM users WHERE id = '{user_id}'
        """))
        await db_session.commit()
        
        # Verify tasks are deleted
        result = await db_session.execute(
            select(Task).where(Task.user_id == user_id)
        )
        tasks = result.scalars().all()
        assert len(tasks) == 0


class TestTaskStatusEnum:
    """Test TaskStatus enum usage."""
    
    async def test_all_enum_values_valid(self, db_session: AsyncSession):
        """Test that all TaskStatus enum values are valid."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Test each enum value
        for status in TaskStatus:
            task = Task(
                user_id=user_id,
                task_type=f"test_{status.value}",
                status=status,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            assert task.status == status
            await db_session.delete(task)
            await db_session.commit()
    
    async def test_enum_serialization(self):
        """Test that TaskStatus serializes correctly."""
        assert str(TaskStatus.pending) == "pending"
        assert TaskStatus.pending.value == "pending"
        assert not isinstance(TaskStatus.pending.value, int)
        
        assert str(TaskStatus.running) == "running"
        assert str(TaskStatus.completed) == "completed"
        assert str(TaskStatus.failed) == "failed"
        assert str(TaskStatus.cancelled) == "cancelled"


class TestPriorityEnum:
    """Test Priority enum usage."""
    
    async def test_all_priority_values_valid(self, db_session: AsyncSession):
        """Test that all Priority enum values are valid."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Test each priority value
        for priority in Priority:
            task = Task(
                user_id=user_id,
                task_type=f"test_{priority.value}",
                priority=priority,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            assert task.priority == priority
            await db_session.delete(task)
            await db_session.commit()
    
    async def test_priority_serialization(self):
        """Test that Priority serializes correctly."""
        assert str(Priority.low) == "low"
        assert str(Priority.normal) == "normal"
        assert str(Priority.high) == "high"
        assert str(Priority.critical) == "critical"


class TestJSONBValidation:
    """Test JSONB field validation for payload and result."""
    
    async def test_payload_accepts_dict(self, db_session: AsyncSession):
        """Test that payload accepts dictionary."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        task = Task(
            user_id=user_id,
            task_type="test",
            payload={"key": "value", "nested": {"inner": True}},
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert isinstance(task.payload, dict)
        assert task.payload["key"] == "value"
        assert task.payload["nested"]["inner"] is True
    
    async def test_result_accepts_complex_structure(self, db_session: AsyncSession):
        """Test that result accepts complex nested structures."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        complex_result = {
            "summary": "Task completed successfully",
            "findings": [
                {"title": "Finding 1", "confidence": 0.95},
                {"title": "Finding 2", "confidence": 0.87},
            ],
            "metadata": {
                "sources": 5,
                "processing_time_ms": 1234,
                "model_used": "gpt-4",
            },
        }
        
        task = Task(
            user_id=user_id,
            task_type="analysis",
            status=TaskStatus.completed,
            result=complex_result,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert isinstance(task.result, dict)
        assert len(task.result["findings"]) == 2
        assert task.result["metadata"]["sources"] == 5
    
    async def test_payload_and_result_nullable(self, db_session: AsyncSession):
        """Test that payload and result are nullable."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        task = Task(
            user_id=user_id,
            task_type="test",
            payload=None,
            result=None,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.payload is None
        assert task.result is None


class TestScheduledTasks:
    """Test scheduled task functionality."""
    
    async def test_scheduled_task_creation(self, db_session: AsyncSession):
        """Test creating a scheduled task."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        future_time = datetime.now(timezone.utc)
        
        task = Task(
            user_id=user_id,
            task_type="scheduled_task",
            status=TaskStatus.pending,
            scheduled_at=future_time,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.scheduled_at is not None
        assert task.status == TaskStatus.pending
    
    async def test_partial_index_for_scheduled_tasks(self, db_session: AsyncSession):
        """Test that partial index works for scheduled pending tasks."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create scheduled pending task
        task1 = Task(
            user_id=user_id,
            task_type="scheduled1",
            status=TaskStatus.pending,
            scheduled_at=datetime.now(timezone.utc),
        )
        db_session.add(task1)
        
        # Create non-scheduled pending task
        task2 = Task(
            user_id=user_id,
            task_type="not_scheduled",
            status=TaskStatus.pending,
        )
        db_session.add(task2)
        
        # Create scheduled completed task
        task3 = Task(
            user_id=user_id,
            task_type="completed",
            status=TaskStatus.completed,
            scheduled_at=datetime.now(timezone.utc),
        )
        db_session.add(task3)
        
        await db_session.commit()
        
        # Query should use partial index for scheduled pending tasks
        result = await db_session.execute(
            select(Task).where(
                Task.status == TaskStatus.pending,
                Task.scheduled_at != None
            )
        )
        scheduled_tasks = result.scalars().all()
        
        assert len(scheduled_tasks) == 1
        assert scheduled_tasks[0].id == task1.id


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_task_create_validation(self):
        """Test TaskCreate model validation."""
        from db.models.task import TaskCreate
        
        user_id = gen_random_uuid()
        
        data = {
            "user_id": user_id,
            "task_type": "research",
            "status": TaskStatus.pending,
            "priority": Priority.high,
            "payload": {"query": "test query"},
            "max_retries": 5,
        }
        model = TaskCreate(**data)
        
        assert model.user_id == user_id
        assert model.task_type == "research"
        assert model.status == TaskStatus.pending
        assert model.priority == Priority.high
        assert model.payload == {"query": "test query"}
        assert model.max_retries == 5
    
    def test_task_update_validation(self):
        """Test TaskUpdate model validation."""
        from db.models.task import TaskUpdate
        
        data = {
            "status": TaskStatus.running,
            "started_at": datetime.now(timezone.utc),
            "retry_count": 1,
        }
        model = TaskUpdate(**data)
        
        assert model.status == TaskStatus.running
        assert model.retry_count == 1
    
    def test_task_status_string_coercion(self):
        """Test that string values are coerced to TaskStatus enum."""
        from db.models.task import TaskCreate
        
        user_id = gen_random_uuid()
        
        # Pass status as string - should be coerced
        data = {
            "user_id": user_id,
            "task_type": "test",
            "status": "running",  # String, not enum
        }
        model = TaskCreate(**data)
        
        assert model.status == TaskStatus.running
        assert isinstance(model.status, TaskStatus)
    
    def test_priority_string_coercion(self):
        """Test that string values are coerced to Priority enum."""
        from db.models.task import TaskCreate
        
        user_id = gen_random_uuid()
        
        # Pass priority as string - should be coerced
        data = {
            "user_id": user_id,
            "task_type": "test",
            "priority": "critical",  # String, not enum
        }
        model = TaskCreate(**data)
        
        assert model.priority == Priority.critical
        assert isinstance(model.priority, Priority)
