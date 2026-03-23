# pyright: reportMissingImports=false
"""
Tests for dead letter queue database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and DLQ workflow for dead_letter_queue table.
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
from db.entity.dead_letter_queue_entity import DeadLetterQueue
from db.entity.task_entity import Task
from db.entity.task_queue_entity import TaskQueue
from db.entity.user_entity import User
from db.entity.llm_endpoint_entity import LLMEndpointGroup  # noqa: F401 - Import for relationship resolution
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
        
        # Create dead_letter_queue table with all constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dead_letter_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                original_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
                original_queue_entry_id UUID REFERENCES task_queue(id) ON DELETE CASCADE,
                original_payload_json JSONB NOT NULL,
                failure_reason TEXT NOT NULL,
                failure_details_json JSONB NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TIMESTAMPTZ,
                dead_lettered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                resolved_at TIMESTAMPTZ,
                resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_dead_letter_queue_retry_count CHECK (retry_count >= 0)
            )
        """))
        
        # Create indexes for tasks
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
        
        # Create indexes for task_queue
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
        
        # Create indexes for dead_letter_queue
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_dead_letter_queue_original_task_id 
            ON dead_letter_queue(original_task_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_dead_letter_queue_original_queue_entry_id 
            ON dead_letter_queue(original_queue_entry_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_dead_letter_queue_resolved_by 
            ON dead_letter_queue(resolved_by)
        """))
        
        # Create partial indexes for dead_letter_queue
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_dlq_unresolved
            ON dead_letter_queue(created_at DESC)
            WHERE is_active = true
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_dlq_resolved
            ON dead_letter_queue(resolved_at DESC)
            WHERE resolved_at IS NOT NULL
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS dead_letter_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS task_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestDeadLetterQueueSchema:
    """Test dead_letter_queue schema creation and structure."""
    
    async def test_dlq_table_exists(self, db_session: AsyncSession):
        """Test that the dead_letter_queue table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'dead_letter_queue'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "dead_letter_queue"
    
    async def test_dlq_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in dead_letter_queue table."""
        expected_columns = {
            'id', 'original_task_id', 'original_queue_entry_id',
            'original_payload_json', 'failure_reason', 'failure_details_json',
            'retry_count', 'last_attempt_at', 'dead_lettered_at',
            'resolved_at', 'resolved_by', 'is_active', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'dead_letter_queue'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_dlq_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'dead_letter_queue'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'ix_dead_letter_queue_original_task_id' in indexes
        assert 'ix_dead_letter_queue_original_queue_entry_id' in indexes
        assert 'ix_dead_letter_queue_resolved_by' in indexes
        assert 'idx_dlq_unresolved' in indexes
        assert 'idx_dlq_resolved' in indexes
    
    async def test_dlq_partial_indexes_filter_correctly(self, db_session: AsyncSession):
        """Test that partial indexes only include appropriate rows."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        
        queue_entry_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO task_queue (id, task_id, status) 
            VALUES ('{queue_entry_id}', '{task_id}', 'failed')
        """))
        
        # Create active DLQ entry
        dlq_active = DeadLetterQueue(
            original_task_id=task_id,
            original_queue_entry_id=queue_entry_id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test error"},
            is_active=True,
        )
        db_session.add(dlq_active)
        
        # Create resolved DLQ entry
        dlq_resolved = DeadLetterQueue(
            original_task_id=task_id,
            original_queue_entry_id=queue_entry_id,
            original_payload_json={"task": "test2"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test error2"},
            is_active=False,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=user_id,
        )
        db_session.add(dlq_resolved)
        
        await db_session.commit()
        
        # Verify idx_dlq_unresolved only includes active items
        result = await db_session.execute(
            text("""
                EXPLAIN (ANALYZE, FORMAT JSON)
                SELECT * FROM dead_letter_queue
                WHERE is_active = true
                ORDER BY created_at DESC
            """)
        )
        plan = result.scalar_one()
        # Should use idx_dlq_unresolved index
        assert 'idx_dlq_unresolved' in str(plan)
        
        # Verify idx_dlq_resolved only includes resolved items
        result = await db_session.execute(
            text("""
                EXPLAIN (ANALYZE, FORMAT JSON)
                SELECT * FROM dead_letter_queue
                WHERE resolved_at IS NOT NULL
                ORDER BY resolved_at DESC
            """)
        )
        plan = result.scalar_one()
        # Should use idx_dlq_resolved index
        assert 'idx_dlq_resolved' in str(plan)


class TestDeadLetterQueueCRUD:
    """Test CRUD operations for DeadLetterQueue model."""
    
    async def test_create_dlq_entry_minimal(self, db_session: AsyncSession):
        """Test creating a DLQ entry with minimal required fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json={"task": "test"},
            failure_reason="MaxRetriesExceeded",
            failure_details_json={"error": "test error", "attempts": 3},
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        assert dlq_entry.id is not None
        assert isinstance(dlq_entry.id, UUID)
        assert dlq_entry.original_task_id == task_id
        assert dlq_entry.failure_reason == "MaxRetriesExceeded"
        assert dlq_entry.retry_count == 0
        assert dlq_entry.is_active is True
        assert dlq_entry.resolved_at is None
        assert dlq_entry.resolved_by is None
    
    async def test_create_dlq_entry_full(self, db_session: AsyncSession):
        """Test creating a DLQ entry with all fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        
        queue_entry_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO task_queue (id, task_id, status) 
            VALUES ('{queue_entry_id}', '{task_id}', 'failed')
        """))
        await db_session.commit()
        
        now = datetime.now(timezone.utc)
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_queue_entry_id=queue_entry_id,
            original_payload_json={
                "task_id": str(task_id),
                "task_type": "research",
                "payload": {"query": "test"},
                "status": "failed",
            },
            failure_reason="ConnectionTimeout",
            failure_details_json={
                "error": "Connection timed out after 30s",
                "stack_trace": "File \"app.py\", line 42, in execute\n  raise TimeoutError",
                "retry_attempts": 3,
                "last_error_at": now.isoformat(),
            },
            retry_count=3,
            last_attempt_at=now,
            is_active=True,
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        assert dlq_entry.original_queue_entry_id == queue_entry_id
        assert dlq_entry.retry_count == 3
        assert dlq_entry.last_attempt_at is not None
        assert dlq_entry.original_payload_json["task_type"] == "research"
        assert "stack_trace" in dlq_entry.failure_details_json
    
    async def test_update_dlq_entry_resolve(self, db_session: AsyncSession):
        """Test resolving a DLQ entry (admin workflow)."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        # Resolve the DLQ entry
        dlq_entry.is_active = False
        dlq_entry.resolved_at = datetime.now(timezone.utc)
        dlq_entry.resolved_by = user_id
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        assert dlq_entry.is_active is False
        assert dlq_entry.resolved_at is not None
        assert dlq_entry.resolved_by == user_id
    
    async def test_dlq_original_payload_preserved(self, db_session: AsyncSession):
        """Test that original payload is properly preserved in JSONB."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        complex_payload = {
            "task_id": str(task_id),
            "task_type": "complex_analysis",
            "payload": {
                "query": "Complex multi-step analysis",
                "parameters": {
                    "depth": 5,
                    "sources": ["source1", "source2"],
                    "filters": {"date_from": "2026-01-01", "date_to": "2026-03-22"},
                },
            },
            "metadata": {
                "created_by": "user-123",
                "version": "1.0",
            },
        }
        
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json=complex_payload,
            failure_reason="ValidationError",
            failure_details_json={
                "validation_errors": [
                    {"field": "query", "error": "Too long"},
                    {"field": "parameters.depth", "error": "Must be <= 3"},
                ],
            },
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        # Verify payload is preserved exactly
        assert dlq_entry.original_payload_json == complex_payload
        assert dlq_entry.original_payload_json["payload"]["parameters"]["depth"] == 5
        assert len(dlq_entry.original_payload_json["metadata"]["sources"]) == 2


class TestDeadLetterQueueForeignKeys:
    """Test foreign key constraints and behaviors."""
    
    async def test_fk_original_task_set_null_on_delete(self, db_session: AsyncSession):
        """Test that original_task_id uses SET NULL (preserves DLQ when task deleted)."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        original_dlq_id = dlq_entry.id
        assert dlq_entry.original_task_id == task_id
        
        # Delete the original task
        await db_session.execute(text(f"""
            DELETE FROM tasks WHERE id = '{task_id}'
        """))
        await db_session.commit()
        
        # Verify DLQ entry still exists with NULL original_task_id
        result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.id == original_dlq_id)
        )
        dlq_entry = result.scalar_one()
        assert dlq_entry is not None
        assert dlq_entry.original_task_id is None
    
    async def test_fk_original_queue_entry_cascade_on_delete(self, db_session: AsyncSession):
        """Test that original_queue_entry_id uses CASCADE (DLQ entry deleted with queue)."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        
        queue_entry_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO task_queue (id, task_id, status) 
            VALUES ('{queue_entry_id}', '{task_id}', 'failed')
        """))
        await db_session.commit()
        
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_queue_entry_id=queue_entry_id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        # Delete the original queue entry
        await db_session.execute(text(f"""
            DELETE FROM task_queue WHERE id = '{queue_entry_id}'
        """))
        await db_session.commit()
        
        # Verify DLQ entry is also deleted (CASCADE)
        result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.original_queue_entry_id == queue_entry_id)
        )
        dlq_entries = result.scalars().all()
        assert len(dlq_entries) == 0
    
    async def test_fk_resolved_by_set_null_on_user_delete(self, db_session: AsyncSession):
        """Test that resolved_by uses SET NULL (preserves DLQ when user deleted)."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            is_active=False,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=user_id,
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        original_dlq_id = dlq_entry.id
        assert dlq_entry.resolved_by == user_id
        
        # Delete the resolving user
        await db_session.execute(text(f"""
            DELETE FROM users WHERE id = '{user_id}'
        """))
        await db_session.commit()
        
        # Verify DLQ entry still exists with NULL resolved_by
        result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.id == original_dlq_id)
        )
        dlq_entry = result.scalar_one()
        assert dlq_entry is not None
        assert dlq_entry.resolved_by is None


class TestDeadLetterQueueWorkflow:
    """Test DLQ workflow scenarios."""
    
    async def test_creation_on_failure(self, db_session: AsyncSession):
        """Test DLQ entry creation when task fails after max retries."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status, retry_count, max_retries) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed', 3, 3)
        """))
        
        queue_entry_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO task_queue (id, task_id, status, retry_count, max_retries, error_message) 
            VALUES ('{queue_entry_id}', '{task_id}', 'failed', 3, 3, 'Max retries exceeded')
        """))
        await db_session.commit()
        
        # Simulate application creating DLQ entry after max retries
        last_attempt = datetime.now(timezone.utc)
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_queue_entry_id=queue_entry_id,
            original_payload_json={
                "task_id": str(task_id),
                "task_type": "test_task",
                "retry_count": 3,
            },
            failure_reason="MaxRetriesExceeded",
            failure_details_json={
                "error": "Max retries exceeded",
                "error_message": "Max retries exceeded",
                "retry_attempts": [
                    {"attempt": 1, "error": "Timeout"},
                    {"attempt": 2, "error": "Timeout"},
                    {"attempt": 3, "error": "Timeout"},
                ],
            },
            retry_count=3,
            last_attempt_at=last_attempt,
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        assert dlq_entry.failure_reason == "MaxRetriesExceeded"
        assert dlq_entry.retry_count == 3
        assert dlq_entry.is_active is True
        assert len(dlq_entry.failure_details_json["retry_attempts"]) == 3
    
    async def test_resolution_flow_with_audit_trail(self, db_session: AsyncSession):
        """Test complete resolution workflow with audit trail."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        # Create DLQ entry
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json={"task": "test"},
            failure_reason="ConnectionTimeout",
            failure_details_json={"error": "Connection timed out"},
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        # Admin reviews and resolves the issue
        resolution_time = datetime.now(timezone.utc)
        dlq_entry.is_active = False
        dlq_entry.resolved_at = resolution_time
        dlq_entry.resolved_by = user_id
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        # Verify audit trail
        assert dlq_entry.is_active is False
        assert dlq_entry.resolved_at is not None
        assert dlq_entry.resolved_by == user_id
        assert dlq_entry.resolved_at >= dlq_entry.dead_lettered_at
        
        # Verify we can query resolved items
        result = await db_session.execute(
            select(DeadLetterQueue)
            .where(DeadLetterQueue.resolved_by == user_id)
            .order_by(DeadLetterQueue.resolved_at.desc())
        )
        resolved_entries = result.scalars().all()
        assert len(resolved_entries) == 1
        assert resolved_entries[0].id == dlq_entry.id
    
    async def test_original_context_preserved_after_task_deletion(self, db_session: AsyncSession):
        """Test that original context remains accessible even if task is deleted."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        original_payload = {
            "task_id": str(task_id),
            "task_type": "critical_analysis",
            "payload": {
                "query": "Critical business analysis",
                "priority": "high",
                "data_sources": ["db1", "db2", "db3"],
            },
            "metadata": {
                "business_unit": "finance",
                "report_id": "RPT-2026-001",
            },
        }
        
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status, payload) 
            VALUES ('{task_id}', '{user_id}', 'critical_analysis', 'failed', '{str(original_payload).replace("'", "\"")}')
        """))
        await db_session.commit()
        
        # Create DLQ entry with full context
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json=original_payload,
            failure_reason="DataAccessError",
            failure_details_json={
                "error": "Failed to access data source db2",
                "affected_sources": ["db2"],
                "partial_results": True,
            },
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        
        # Store DLQ ID for later retrieval
        dlq_id = dlq_entry.id
        
        # Simulate task retention policy deleting old failed tasks
        await db_session.execute(text(f"""
            DELETE FROM tasks WHERE id = '{task_id}'
        """))
        await db_session.commit()
        
        # Verify we can still access the original context from DLQ
        result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.id == dlq_id)
        )
        dlq_entry = result.scalar_one()
        
        assert dlq_entry is not None
        assert dlq_entry.original_task_id is None  # SET NULL on task delete
        assert dlq_entry.original_payload_json == original_payload
        assert dlq_entry.original_payload_json["task_type"] == "critical_analysis"
        assert dlq_entry.original_payload_json["metadata"]["report_id"] == "RPT-2026-001"
        
        # Context is preserved for potential reprocessing
        assert "payload" in dlq_entry.original_payload_json
        assert "data_sources" in dlq_entry.original_payload_json["payload"]


class TestDeadLetterQueuePydanticModels:
    """Test Pydantic model validation."""
    
    async def test_dead_letter_queue_create_validation(self):
        """Test DeadLetterQueueCreate model validation."""
        from db.models.dead_letter_queue import DeadLetterQueueCreate
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=uuid4(),
            original_queue_entry_id=uuid4(),
            original_payload_json={"task": "test"},
            failure_reason="MaxRetriesExceeded",
            failure_details_json={"error": "test", "attempts": 3},
            retry_count=3,
            is_active=True,
        )
        
        assert dlq_create.failure_reason == "MaxRetriesExceeded"
        assert dlq_create.retry_count == 3
        assert dlq_create.is_active is True
    
    async def test_dead_letter_queue_resolve_model(self):
        """Test DeadLetterQueueResolve model for resolution workflow."""
        from db.models.dead_letter_queue import DeadLetterQueueResolve
        
        user_id = uuid4()
        resolve_data = DeadLetterQueueResolve(
            resolved_by=user_id,
            is_active=False,
        )
        
        assert resolve_data.resolved_by == user_id
        assert resolve_data.is_active is False
    
    async def test_dead_letter_queue_full_model(self, db_session: AsyncSession):
        """Test complete DeadLetterQueue model with all fields."""
        from db.models.dead_letter_queue import DeadLetterQueue
        
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type, status) 
            VALUES ('{task_id}', '{user_id}', 'test_task', 'failed')
        """))
        await db_session.commit()
        
        now = datetime.now(timezone.utc)
        dlq_entry = DeadLetterQueue(
            original_task_id=task_id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            retry_count=3,
            last_attempt_at=now,
            dead_lettered_at=now,
            resolved_at=now,
            resolved_by=user_id,
            is_active=False,
        )
        
        assert dlq_entry.id is not None
        assert dlq_entry.failure_reason == "TestFailure"
        assert dlq_entry.resolved_by == user_id
        assert dlq_entry.is_active is False
