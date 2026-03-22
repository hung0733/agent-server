# pyright: reportMissingImports=false
"""
Tests for task queue database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and queue behavior for task_queue table.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.schema.task_queue import TaskQueue
from db.schema.tasks import Task
from db.schema.llm_endpoints import LLMEndpointGroup  # noqa: F401 - Import for relationship resolution
from db.types import TaskStatus, gen_random_uuid


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
        
        # Create task_queue table with all constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
                priority INTEGER NOT NULL DEFAULT 0,
                queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                scheduled_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                claimed_by UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                claimed_at TIMESTAMPTZ,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                error_message TEXT,
                result_json JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_task_queue_retry_count CHECK (retry_count >= 0),
                CONSTRAINT ck_task_queue_max_retries CHECK (max_retries >= 0),
                CONSTRAINT ck_task_queue_priority CHECK (priority >= 0)
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
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_pending
            ON tasks(scheduled_at)
            WHERE status = 'pending'
        """))
        
        # Create task_queue indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_task_queue_task_id ON task_queue(task_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_task_queue_claimed_by ON task_queue(claimed_by)
        """))
        
        # Create partial indexes for task_queue
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_queue_poll
            ON task_queue(priority DESC, scheduled_at ASC)
            WHERE status = 'pending'
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_queue_claimed
            ON task_queue(claimed_by)
            WHERE status = 'running'
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_queue_retry
            ON task_queue(retry_count)
            WHERE status = 'pending'
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS task_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestTaskQueueSchema:
    """Test task_queue schema creation and structure."""
    
    async def test_task_queue_table_exists(self, db_session: AsyncSession):
        """Test that the task_queue table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'task_queue'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "task_queue"
    
    async def test_task_queue_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in task_queue table."""
        expected_columns = {
            'id', 'task_id', 'status', 'priority', 'queued_at',
            'scheduled_at', 'started_at', 'completed_at', 'claimed_by',
            'claimed_at', 'retry_count', 'max_retries', 'error_message',
            'result_json', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'task_queue'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_task_queue_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'task_queue'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'ix_task_queue_task_id' in indexes
        assert 'ix_task_queue_claimed_by' in indexes
        assert 'idx_queue_poll' in indexes
        assert 'idx_queue_claimed' in indexes
        assert 'idx_queue_retry' in indexes


class TestTaskQueueCRUD:
    """Test CRUD operations for TaskQueue model."""
    
    async def test_create_queue_entry_minimal(self, db_session: AsyncSession):
        """Test creating a queue entry with minimal fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.id is not None
        assert isinstance(queue_entry.id, UUID)
        assert queue_entry.task_id == task_id
        assert queue_entry.status == TaskStatus.pending
        assert queue_entry.priority == 0
        assert queue_entry.retry_count == 0
        assert queue_entry.max_retries == 3
    
    async def test_create_queue_entry_full(self, db_session: AsyncSession):
        """Test creating a queue entry with all fields."""
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
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'full_test', 'pending')
        """))
        await db_session.commit()
        
        scheduled_time = datetime.now(timezone.utc) + timedelta(hours=1)
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.pending,
            priority=100,
            scheduled_at=scheduled_time,
            claimed_by=agent_id,
            claimed_at=datetime.now(timezone.utc),
            max_retries=5,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.priority == 100
        assert queue_entry.scheduled_at is not None
        assert queue_entry.claimed_by == agent_id
        assert queue_entry.max_retries == 5
    
    async def test_delete_queue_entry(self, db_session: AsyncSession):
        """Test deleting a queue entry."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(task_id=task_id)
        db_session.add(queue_entry)
        await db_session.commit()
        
        await db_session.delete(queue_entry)
        await db_session.commit()
        
        result = await db_session.execute(
            select(TaskQueue).where(TaskQueue.id == queue_entry.id)
        )
        assert result.scalar_one_or_none() is None


class TestQueuePolling:
    """Test queue polling behavior with priority and scheduled_at."""
    
    async def _setup_test_data(self, db_session: AsyncSession) -> UUID:
        """Helper to set up test user and tasks."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'polluser', 'poll@example.com')
        """))
        return user_id
    
    async def test_priority_ordering(self, db_session: AsyncSession):
        """Test that higher priority tasks are returned first."""
        user_id = await self._setup_test_data(db_session)
        
        # Create tasks with different priorities
        for i in range(5):
            task_id = gen_random_uuid()
            await db_session.execute(text(f"""
                INSERT INTO tasks (id, user_id, task_type, status) 
                VALUES ('{task_id}', '{user_id}', 'task_{i}', 'pending')
            """))
            queue_entry = TaskQueue(
                task_id=task_id,
                priority=i * 10,  # 0, 10, 20, 30, 40
            )
            db_session.add(queue_entry)
        await db_session.commit()
        
        # Query for pending tasks ordered by priority DESC, scheduled_at ASC
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc())
        )
        entries = result.scalars().all()
        
        assert len(entries) == 5
        # Highest priority should be first
        assert entries[0].priority == 40
        assert entries[4].priority == 0
    
    async def test_scheduled_at_ordering(self, db_session: AsyncSession):
        """Test that tasks with earlier scheduled_at are returned first for same priority."""
        user_id = await self._setup_test_data(db_session)
        
        now = datetime.now(timezone.utc)
        
        # Create tasks with same priority but different scheduled times
        for i in range(3):
            task_id = gen_random_uuid()
            await db_session.execute(text(f"""
                INSERT INTO tasks (id, user_id, task_type, status) 
                VALUES ('{task_id}', '{user_id}', 'task_{i}', 'pending')
            """))
            queue_entry = TaskQueue(
                task_id=task_id,
                priority=10,
                scheduled_at=now + timedelta(hours=i),  # 0h, 1h, 2h from now
            )
            db_session.add(queue_entry)
        await db_session.commit()
        
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc())
        )
        entries = result.scalars().all()
        
        assert len(entries) == 3
        # Earliest scheduled should be first
        assert entries[0].scheduled_at < entries[1].scheduled_at
        assert entries[1].scheduled_at < entries[2].scheduled_at
    
    async def test_immediate_vs_scheduled_tasks(self, db_session: AsyncSession):
        """Test that immediate tasks (NULL scheduled_at) are processed before future scheduled."""
        user_id = await self._setup_test_data(db_session)
        
        # Create immediate task (no scheduled_at)
        task_id_immediate = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_immediate}', '{user_id}', 'immediate', 'pending')
        """))
        queue_immediate = TaskQueue(
            task_id=task_id_immediate,
            priority=10,
            scheduled_at=None,  # Immediate
        )
        db_session.add(queue_immediate)
        
        # Create future scheduled task
        task_id_scheduled = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_scheduled}', '{user_id}', 'scheduled', 'pending')
        """))
        queue_scheduled = TaskQueue(
            task_id=task_id_scheduled,
            priority=10,
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db_session.add(queue_scheduled)
        await db_session.commit()
        
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc().nulls_first())
        )
        entries = result.scalars().all()
        
        assert len(entries) == 2
        # Immediate task (NULL scheduled_at) should be first
        assert entries[0].scheduled_at is None
        assert entries[1].scheduled_at is not None


class TestTaskClaiming:
    """Test task claiming functionality."""
    
    async def test_claim_task(self, db_session: AsyncSession):
        """Test claiming a task by an agent."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'claimuser', 'claim@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'ClaimAgent')
        """))
        
        agent_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status) 
            VALUES ('{agent_id}', '{agent_type_id}', '{user_id}', 'idle')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'claim_test', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.pending,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Claim the task
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = agent_id
        queue_entry.claimed_at = datetime.now(timezone.utc)
        queue_entry.started_at = datetime.now(timezone.utc)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.status == TaskStatus.running
        assert queue_entry.claimed_by == agent_id
        assert queue_entry.claimed_at is not None
        assert queue_entry.started_at is not None
    
    async def test_list_claimed_tasks(self, db_session: AsyncSession):
        """Test listing tasks claimed by an agent."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'listuser', 'list@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'ListAgent')
        """))
        
        agent_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status) 
            VALUES ('{agent_id}', '{agent_type_id}', '{user_id}', 'busy')
        """))
        await db_session.commit()
        
        # Create and claim multiple tasks
        for i in range(3):
            task_id = gen_random_uuid()
            await db_session.execute(text(f"""
                INSERT INTO tasks (id, user_id, task_type, status) 
                VALUES ('{task_id}', '{user_id}', 'claimed_{i}', 'running')
            """))
            queue_entry = TaskQueue(
                task_id=task_id,
                status=TaskStatus.running,
                claimed_by=agent_id,
                claimed_at=datetime.now(timezone.utc),
            )
            db_session.add(queue_entry)
        await db_session.commit()
        
        # Query claimed tasks
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.claimed_by == agent_id)
            .where(TaskQueue.status == TaskStatus.running)
        )
        claimed = result.scalars().all()
        
        assert len(claimed) == 3
    
    async def test_claimed_by_set_null_on_agent_delete(self, db_session: AsyncSession):
        """Test that claimed_by is set to NULL when agent is deleted."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'nulluser', 'null@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'NullAgent')
        """))
        
        agent_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status) 
            VALUES ('{agent_id}', '{agent_type_id}', '{user_id}', 'busy')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'null_test', 'running')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.running,
            claimed_by=agent_id,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.claimed_by == agent_id
        
        # Delete agent
        await db_session.execute(text(f"""
            DELETE FROM agent_instances WHERE id = '{agent_id}'
        """))
        await db_session.commit()
        
        # Verify claimed_by is NULL
        await db_session.refresh(queue_entry)
        assert queue_entry.claimed_by is None


class TestCompletionFlow:
    """Test task completion flow."""
    
    async def test_complete_task_success(self, db_session: AsyncSession):
        """Test completing a task successfully."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'compuser', 'comp@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'complete_test', 'running')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Complete the task
        queue_entry.status = TaskStatus.completed
        queue_entry.completed_at = datetime.now(timezone.utc)
        queue_entry.result_json = {
            "output": "Task completed successfully",
            "metrics": {"duration_ms": 5000}
        }
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.status == TaskStatus.completed
        assert queue_entry.completed_at is not None
        assert queue_entry.result_json is not None
        assert queue_entry.result_json["output"] == "Task completed successfully"
    
    async def test_fail_task_with_error(self, db_session: AsyncSession):
        """Test failing a task with error message."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'failuser', 'fail@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'fail_test', 'running')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.running,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Fail the task
        queue_entry.status = TaskStatus.failed
        queue_entry.completed_at = datetime.now(timezone.utc)
        queue_entry.error_message = "Connection timeout after 30 seconds"
        queue_entry.retry_count = 1
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.status == TaskStatus.failed
        assert queue_entry.error_message == "Connection timeout after 30 seconds"
        assert queue_entry.retry_count == 1
    
    async def test_cancel_task(self, db_session: AsyncSession):
        """Test cancelling a task."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'canceluser', 'cancel@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'cancel_test', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.pending,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Cancel the task
        queue_entry.status = TaskStatus.cancelled
        queue_entry.completed_at = datetime.now(timezone.utc)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.status == TaskStatus.cancelled
        assert queue_entry.completed_at is not None


class TestRetryLogic:
    """Test retry logic for failed tasks."""
    
    async def test_retry_count_increments(self, db_session: AsyncSession):
        """Test that retry count increments correctly."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'retryuser', 'retry@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'retry_test', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.pending,
            retry_count=0,
            max_retries=3,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        
        # Simulate retry cycle
        for attempt in range(1, 4):
            queue_entry.status = TaskStatus.running
            await db_session.commit()
            
            # Fail the task
            queue_entry.status = TaskStatus.pending  # Back to pending for retry
            queue_entry.retry_count = attempt
            queue_entry.error_message = f"Attempt {attempt} failed"
            await db_session.commit()
            await db_session.refresh(queue_entry)
            
            assert queue_entry.retry_count == attempt
        
        # Final attempt exceeds max
        queue_entry.status = TaskStatus.running
        await db_session.commit()
        queue_entry.status = TaskStatus.failed
        queue_entry.retry_count = 4
        queue_entry.error_message = "Max retries exceeded"
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.status == TaskStatus.failed
    
    async def test_max_retries_respected(self, db_session: AsyncSession):
        """Test that max_retries is respected."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'maxuser', 'max@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'max_test', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.pending,
            retry_count=2,
            max_retries=2,  # Already at max
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Should not retry anymore
        assert queue_entry.retry_count >= queue_entry.max_retries
    
    async def test_partial_index_for_retry_monitoring(self, db_session: AsyncSession):
        """Test that partial index helps identify pending tasks with retries."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'idxuser', 'idx@example.com')
        """))
        await db_session.commit()
        
        # Create tasks with different retry counts
        for i in range(3):
            task_id = gen_random_uuid()
            await db_session.execute(text(f"""
                INSERT INTO tasks (id, user_id, task_type, status) 
                VALUES ('{task_id}', '{user_id}', 'retry_idx_{i}', 'pending')
            """))
            queue_entry = TaskQueue(
                task_id=task_id,
                status=TaskStatus.pending,
                retry_count=i,  # 0, 1, 2 retries
            )
            db_session.add(queue_entry)
        
        # Create a running task with retry (should NOT be in partial index)
        task_id_running = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_running}', '{user_id}', 'running_retry', 'running')
        """))
        queue_running = TaskQueue(
            task_id=task_id_running,
            status=TaskStatus.running,
            retry_count=5,
        )
        db_session.add(queue_running)
        await db_session.commit()
        
        # Query for pending tasks with retries (should use partial index)
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .where(TaskQueue.retry_count > 0)
        )
        pending_with_retries = result.scalars().all()
        
        # Should only get pending tasks, not the running one
        assert len(pending_with_retries) == 2
        for entry in pending_with_retries:
            assert entry.status == TaskStatus.pending
            assert entry.retry_count > 0


class TestForeignKeys:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_task_id_enforced(self, db_session: AsyncSession):
        """Test that task_id FK constraint is enforced."""
        fake_task_id = uuid4()
        
        queue_entry = TaskQueue(
            task_id=fake_task_id,
        )
        db_session.add(queue_entry)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_task(self, db_session: AsyncSession):
        """Test that deleting task cascades to queue entries."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'cascadeuser', 'cascade@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'cascade_test', 'pending')
        """))
        await db_session.commit()
        
        # Create queue entry
        queue_entry = TaskQueue(
            task_id=task_id,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        queue_entry_id = queue_entry.id
        
        # Delete task
        await db_session.execute(text(f"""
            DELETE FROM tasks WHERE id = '{task_id}'
        """))
        await db_session.commit()
        
        # Verify queue entry is deleted
        result = await db_session.execute(
            select(TaskQueue).where(TaskQueue.id == queue_entry_id)
        )
        assert result.scalar_one_or_none() is None


class TestStatusEnum:
    """Test TaskStatus enum usage in queue."""
    
    async def test_all_enum_values_valid(self, db_session: AsyncSession):
        """Test that all TaskStatus enum values are valid."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'enumuser', 'enum@example.com')
        """))
        await db_session.commit()
        
        # Test each enum value
        for status in TaskStatus:
            task_id = gen_random_uuid()
            await db_session.execute(text(f"""
                INSERT INTO tasks (id, user_id, task_type, status) 
                VALUES ('{task_id}', '{user_id}', 'enum_{status.value}', 'pending')
            """))
            queue_entry = TaskQueue(
                task_id=task_id,
                status=status,
            )
            db_session.add(queue_entry)
            await db_session.commit()
            await db_session.refresh(queue_entry)
            
            assert queue_entry.status == status
            await db_session.delete(queue_entry)
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


class TestJSONBValidation:
    """Test JSONB field validation for result_json."""
    
    async def test_result_json_accepts_dict(self, db_session: AsyncSession):
        """Test that result_json accepts dictionary."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'jsonuser', 'json@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'json_test', 'completed')
        """))
        await db_session.commit()
        
        result_data = {
            "output": "Task completed",
            "metrics": {
                "duration_ms": 1234,
                "tokens_used": 500,
            },
            "artifacts": [
                {"name": "file1.py", "size": 1024},
                {"name": "file2.py", "size": 2048},
            ],
        }
        
        queue_entry = TaskQueue(
            task_id=task_id,
            status=TaskStatus.completed,
            result_json=result_data,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert isinstance(queue_entry.result_json, dict)
        assert queue_entry.result_json["output"] == "Task completed"
        assert len(queue_entry.result_json["artifacts"]) == 2
    
    async def test_result_json_nullable(self, db_session: AsyncSession):
        """Test that result_json is nullable."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'nulljson', 'nulljson@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'null_json', 'pending')
        """))
        await db_session.commit()
        
        queue_entry = TaskQueue(
            task_id=task_id,
            result_json=None,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.result_json is None


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_task_queue_create_validation(self):
        """Test TaskQueueCreate model validation."""
        from db.models.task_queue import TaskQueueCreate
        
        task_id = gen_random_uuid()
        
        data = {
            "task_id": task_id,
            "status": TaskStatus.pending,
            "priority": 50,
            "max_retries": 5,
        }
        model = TaskQueueCreate(**data)
        
        assert model.task_id == task_id
        assert model.status == TaskStatus.pending
        assert model.priority == 50
        assert model.max_retries == 5
    
    def test_task_queue_update_validation(self):
        """Test TaskQueueUpdate model validation."""
        from db.models.task_queue import TaskQueueUpdate
        
        data = {
            "status": TaskStatus.running,
            "claimed_by": gen_random_uuid(),
            "started_at": datetime.now(timezone.utc),
            "retry_count": 1,
        }
        model = TaskQueueUpdate(**data)
        
        assert model.status == TaskStatus.running
        assert model.retry_count == 1
    
    def test_task_queue_status_string_coercion(self):
        """Test that string values are coerced to TaskStatus enum."""
        from db.models.task_queue import TaskQueueCreate
        
        task_id = gen_random_uuid()
        
        # Pass status as string - should be coerced
        data = {
            "task_id": task_id,
            "status": "running",  # String, not enum
        }
        model = TaskQueueCreate(**data)
        
        assert model.status == TaskStatus.running
        assert isinstance(model.status, TaskStatus)
    
    def test_priority_validation(self):
        """Test that priority must be non-negative."""
        from db.models.task_queue import TaskQueueCreate
        from pydantic import ValidationError
        
        task_id = gen_random_uuid()
        
        # Negative priority should fail
        with pytest.raises(ValidationError):
            TaskQueueCreate(task_id=task_id, priority=-1)
    
    def test_retry_count_validation(self):
        """Test that retry_count must be non-negative."""
        from db.models.task_queue import TaskQueueCreate
        from pydantic import ValidationError
        
        task_id = gen_random_uuid()
        
        # Negative retry_count should fail
        with pytest.raises(ValidationError):
            TaskQueueCreate(task_id=task_id, retry_count=-1)


class TestPartialIndexPerformance:
    """Test partial index behavior for performance optimization."""
    
    async def test_poll_index_only_includes_pending(self, db_session: AsyncSession):
        """Test that idx_queue_poll only includes pending tasks."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'pollidx', 'pollidx@example.com')
        """))
        await db_session.commit()
        
        # Create pending task
        task_id_pending = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_pending}', '{user_id}', 'pending_task', 'pending')
        """))
        queue_pending = TaskQueue(
            task_id=task_id_pending,
            status=TaskStatus.pending,
            priority=10,
        )
        db_session.add(queue_pending)
        
        # Create running task (should NOT be in partial index)
        task_id_running = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_running}', '{user_id}', 'running_task', 'running')
        """))
        queue_running = TaskQueue(
            task_id=task_id_running,
            status=TaskStatus.running,
            priority=20,  # Higher priority but not pending
        )
        db_session.add(queue_running)
        
        # Create completed task (should NOT be in partial index)
        task_id_completed = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_completed}', '{user_id}', 'completed_task', 'completed')
        """))
        queue_completed = TaskQueue(
            task_id=task_id_completed,
            status=TaskStatus.completed,
            priority=30,  # Highest priority but completed
        )
        db_session.add(queue_completed)
        
        await db_session.commit()
        
        # Query using partial index
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc())
        )
        pending_tasks = result.scalars().all()
        
        # Only pending task should be returned
        assert len(pending_tasks) == 1
        assert pending_tasks[0].status == TaskStatus.pending
    
    async def test_claimed_index_only_includes_running(self, db_session: AsyncSession):
        """Test that idx_queue_claimed only includes running tasks."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'claimedidx', 'claimedidx@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'ClaimedAgent')
        """))
        
        agent_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status) 
            VALUES ('{agent_id}', '{agent_type_id}', '{user_id}', 'busy')
        """))
        await db_session.commit()
        
        # Create running task claimed by agent
        task_id_running = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_running}', '{user_id}', 'running_claimed', 'running')
        """))
        queue_running = TaskQueue(
            task_id=task_id_running,
            status=TaskStatus.running,
            claimed_by=agent_id,
        )
        db_session.add(queue_running)
        
        # Create pending task also with claimed_by (unusual but possible)
        task_id_pending = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id_pending}', '{user_id}', 'pending_claimed', 'pending')
        """))
        queue_pending = TaskQueue(
            task_id=task_id_pending,
            status=TaskStatus.pending,
            claimed_by=agent_id,
        )
        db_session.add(queue_pending)
        
        await db_session.commit()
        
        # Query using partial index for claimed running tasks
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.claimed_by == agent_id)
            .where(TaskQueue.status == TaskStatus.running)
        )
        claimed_running = result.scalars().all()
        
        # Only running task should be in this result
        assert len(claimed_running) == 1
        assert claimed_running[0].status == TaskStatus.running