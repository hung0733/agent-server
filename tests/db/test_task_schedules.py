# pyright: reportMissingImports=false
"""
Tests for task schedule database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, schedule expression validation, and partial index functionality.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.entity.task_schedule_entity import TaskSchedule
from db.types import ScheduleType, gen_random_uuid


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
        
        # Create task_schedules table with all constraints
        await conn.execute(text(r"""
            CREATE TABLE IF NOT EXISTS task_schedules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_template_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                schedule_type TEXT NOT NULL DEFAULT 'cron'
                    CHECK (schedule_type IN ('once', 'interval', 'cron')),
                schedule_expression TEXT NOT NULL,
                next_run_at TIMESTAMPTZ,
                last_run_at TIMESTAMPTZ,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_task_schedules_cron_format CHECK (
                    CASE 
                        WHEN schedule_type = 'cron' THEN
                            schedule_expression ~ '^(\*|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*|\*/[0-9]+)( +(\*|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*|\*/[0-9]+)){4}$'
                        ELSE TRUE
                    END
                ),
                CONSTRAINT ck_task_schedules_interval_format CHECK (
                    CASE 
                        WHEN schedule_type = 'interval' THEN
                            schedule_expression ~ '^P(\\d+Y)?(\\d+M)?(\\d+D)?(T(\\d+H)?(\\d+M)?(\\d+S)?)?$|^P\\d+W$'
                        ELSE TRUE
                    END
                ),
                CONSTRAINT ck_task_schedules_once_format CHECK (
                    CASE 
                        WHEN schedule_type = 'once' THEN
                            schedule_expression ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
                        ELSE TRUE
                    END
                ),
                CONSTRAINT uq_task_schedules_template UNIQUE (task_template_id)
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_task_schedules_task_template_id 
            ON task_schedules(task_template_id)
        """))
        
        # Create partial index for next_run_at
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_schedules_next_run
            ON task_schedules(next_run_at ASC)
            WHERE is_active = true AND next_run_at IS NOT NULL
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS task_schedules"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestTaskScheduleSchema:
    """Test task_schedules schema creation and structure."""
    
    async def test_task_schedules_table_exists(self, db_session: AsyncSession):
        """Test that the task_schedules table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'task_schedules'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "task_schedules"
    
    async def test_task_schedules_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in task_schedules table."""
        expected_columns = {
            'id', 'task_template_id', 'schedule_type', 'schedule_expression',
            'next_run_at', 'last_run_at', 'is_active', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'task_schedules'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_task_schedules_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'task_schedules'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'ix_task_schedules_task_template_id' in indexes
        assert 'idx_schedules_next_run' in indexes
    
    async def test_unique_constraint_on_task_template_id(self, db_session: AsyncSession):
        """Test that unique constraint exists on task_template_id."""
        result = await db_session.execute(
            text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'task_schedules' 
                AND constraint_type = 'UNIQUE'
            """)
        )
        constraints = {row[0] for row in result.fetchall()}
        
        assert 'uq_task_schedules_template' in constraints


class TestScheduleTypeValidation:
    """Test schedule_type enum validation."""
    
    async def test_all_enum_values_valid(self, db_session: AsyncSession):
        """Test that all ScheduleType enum values are valid."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        # Create a task template
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'scheduled_task')
        """))
        await db_session.commit()
        
        # Test each enum value with valid expressions
        test_cases = [
            (ScheduleType.cron, "0 12 * * *"),
            (ScheduleType.interval, "PT1H"),
            (ScheduleType.once, "2026-03-22T12:00:00Z"),
        ]
        
        for schedule_type, expression in test_cases:
            schedule = TaskSchedule(
                task_template_id=task_id,
                schedule_type=schedule_type,
                schedule_expression=expression,
            )
            db_session.add(schedule)
            await db_session.commit()
            await db_session.refresh(schedule)
            
            assert schedule.schedule_type == schedule_type
            await db_session.delete(schedule)
            await db_session.commit()


class TestCronExpressionValidation:
    """Test cron expression format validation."""
    
    async def test_valid_cron_expressions(self, db_session: AsyncSession):
        """Test that valid cron expressions are accepted."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        valid_cron_exprs = [
            "0 12 * * *",        # Daily at noon
            "*/5 * * * *",       # Every 5 minutes
            "0 0 1 1 *",         # Yearly on Jan 1
            "30 8 * * 1-5",      # Weekdays at 8:30
            "0,30 * * * *",      # Every hour at 0 and 30 minutes
        ]
        
        for expr in valid_cron_exprs:
            schedule = TaskSchedule(
                task_template_id=task_id,
                schedule_type=ScheduleType.cron,
                schedule_expression=expr,
            )
            db_session.add(schedule)
            await db_session.commit()
            await db_session.refresh(schedule)
            assert schedule.schedule_expression == expr
            await db_session.delete(schedule)
            await db_session.commit()
    
    async def test_invalid_cron_expression_rejected(self, db_session: AsyncSession):
        """Test that invalid cron expressions are rejected."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        invalid_expr = "invalid cron"
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression=invalid_expr,
        )
        db_session.add(schedule)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestIntervalExpressionValidation:
    """Test ISO 8601 interval expression format validation."""
    
    async def test_valid_interval_expressions(self, db_session: AsyncSession):
        """Test that valid interval expressions are accepted."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        valid_intervals = [
            "PT5M",    # 5 minutes
            "PT1H",    # 1 hour
            "P1D",     # 1 day
            "P1W",     # 1 week
            "PT2H30M", # 2 hours 30 minutes
            "P1DT12H", # 1 day 12 hours
        ]
        
        for expr in valid_intervals:
            schedule = TaskSchedule(
                task_template_id=task_id,
                schedule_type=ScheduleType.interval,
                schedule_expression=expr,
            )
            db_session.add(schedule)
            await db_session.commit()
            await db_session.refresh(schedule)
            assert schedule.schedule_expression == expr
            await db_session.delete(schedule)
            await db_session.commit()
    
    async def test_invalid_interval_expression_rejected(self, db_session: AsyncSession):
        """Test that invalid interval expressions are rejected."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        invalid_expr = "every hour"
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.interval,
            schedule_expression=invalid_expr,
        )
        db_session.add(schedule)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestOnceExpressionValidation:
    """Test ISO 8601 timestamp expression format validation."""
    
    async def test_valid_once_expressions(self, db_session: AsyncSession):
        """Test that valid timestamp expressions are accepted."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        valid_timestamps = [
            "2026-03-22T12:00:00Z",
            "2026-03-22T12:00:00+00:00",
            "2026-03-22T12:00:00-05:00",
            "2026-03-22T12:00:00.123Z",
        ]
        
        for expr in valid_timestamps:
            schedule = TaskSchedule(
                task_template_id=task_id,
                schedule_type=ScheduleType.once,
                schedule_expression=expr,
            )
            db_session.add(schedule)
            await db_session.commit()
            await db_session.refresh(schedule)
            assert schedule.schedule_expression == expr
            await db_session.delete(schedule)
            await db_session.commit()
    
    async def test_invalid_once_expression_rejected(self, db_session: AsyncSession):
        """Test that invalid timestamp expressions are rejected."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        invalid_expr = "tomorrow at noon"
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.once,
            schedule_expression=invalid_expr,
        )
        db_session.add(schedule)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestTaskScheduleCRUD:
    """Test CRUD operations for TaskSchedule model."""
    
    async def test_create_schedule_minimal(self, db_session: AsyncSession):
        """Test creating a schedule with minimal fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'scheduled_task')
        """))
        await db_session.commit()
        
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 12 * * *",
        )
        db_session.add(schedule)
        await db_session.commit()
        await db_session.refresh(schedule)
        
        assert schedule.id is not None
        assert isinstance(schedule.id, UUID)
        assert schedule.task_template_id == task_id
        assert schedule.schedule_type == ScheduleType.cron
        assert schedule.schedule_expression == "0 12 * * *"
        assert schedule.is_active is True
        assert schedule.next_run_at is None
        assert schedule.last_run_at is None
    
    async def test_create_schedule_full(self, db_session: AsyncSession):
        """Test creating a schedule with all fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'scheduled_task')
        """))
        await db_session.commit()
        
        now = datetime.now(timezone.utc)
        
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.interval,
            schedule_expression="PT1H",
            next_run_at=now,
            last_run_at=None,
            is_active=True,
        )
        db_session.add(schedule)
        await db_session.commit()
        await db_session.refresh(schedule)
        
        assert schedule.next_run_at is not None
        assert schedule.is_active is True
        assert schedule.schedule_type == ScheduleType.interval
    
    async def test_update_schedule_activation(self, db_session: AsyncSession):
        """Test toggling schedule activation status."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 * * * *",
            is_active=True,
        )
        db_session.add(schedule)
        await db_session.commit()
        
        original_updated_at = schedule.updated_at
        await asyncio.sleep(0.01)
        
        # Deactivate schedule
        schedule.is_active = False
        await db_session.commit()
        await db_session.refresh(schedule)
        
        assert schedule.is_active is False
        assert schedule.updated_at > original_updated_at
        
        # Reactivate schedule
        original_updated_at = schedule.updated_at
        await asyncio.sleep(0.01)
        
        schedule.is_active = True
        await db_session.commit()
        await db_session.refresh(schedule)
        
        assert schedule.is_active is True
        assert schedule.updated_at > original_updated_at
    
    async def test_update_schedule_execution_times(self, db_session: AsyncSession):
        """Test updating last_run_at and next_run_at on schedule execution."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 * * * *",
            next_run_at=datetime.now(timezone.utc),
        )
        db_session.add(schedule)
        await db_session.commit()
        
        # Simulate schedule execution
        original_last_run = schedule.last_run_at
        schedule.last_run_at = datetime.now(timezone.utc)
        # Next run would be computed by scheduler service
        await db_session.commit()
        await db_session.refresh(schedule)
        
        assert schedule.last_run_at is not None
        if original_last_run is not None:
            # Both are datetime objects, safe to compare
            assert schedule.last_run_at > original_last_run  # type: ignore[misc]
    
    async def test_delete_schedule(self, db_session: AsyncSession):
        """Test deleting a schedule."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 0 * * *",
        )
        db_session.add(schedule)
        await db_session.commit()
        
        await db_session.delete(schedule)
        await db_session.commit()
        
        result = await db_session.execute(
            select(TaskSchedule).where(TaskSchedule.id == schedule.id)
        )
        assert result.scalar_one_or_none() is None


class TestForeignKeyConstraints:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_task_template_id_enforced(self, db_session: AsyncSession):
        """Test that task_template_id FK constraint is enforced."""
        fake_task_id = uuid4()
        
        schedule = TaskSchedule(
            task_template_id=fake_task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 0 * * *",
        )
        db_session.add(schedule)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_task_template(self, db_session: AsyncSession):
        """Test that deleting task template cascades to schedules."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create task template
        task = TaskSchedule.__table__.c  # noqa: F841
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'template_task')
        """))
        
        # Create schedule
        schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 0 * * *",
        )
        db_session.add(schedule)
        await db_session.commit()
        
        # Delete task template
        await db_session.execute(text(f"""
            DELETE FROM tasks WHERE id = '{task_id}'
        """))
        await db_session.commit()
        
        # Verify schedule is deleted
        result = await db_session.execute(
            select(TaskSchedule).where(TaskSchedule.task_template_id == task_id)
        )
        schedules = result.scalars().all()
        assert len(schedules) == 0


class TestUniqueConstraint:
    """Test unique constraint on task_template_id."""
    
    async def test_only_one_schedule_per_task(self, db_session: AsyncSession):
        """Test that each task can have only one schedule."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        # Create first schedule
        schedule1 = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 0 * * *",
        )
        db_session.add(schedule1)
        await db_session.commit()
        
        # Try to create second schedule for same task
        schedule2 = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.interval,
            schedule_expression="PT1H",
        )
        db_session.add(schedule2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestPartialIndex:
    """Test partial index functionality for active schedules."""
    
    async def test_partial_index_filters_inactive_schedules(self, db_session: AsyncSession):
        """Test that partial index only includes active schedules with non-NULL next_run_at."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        task_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id}', '{user_id}', 'test')
        """))
        await db_session.commit()
        
        now = datetime.now(timezone.utc)
        
        # Create active schedule with next_run_at (should be in index)
        active_schedule = TaskSchedule(
            task_template_id=task_id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 0 * * *",
            is_active=True,
            next_run_at=now,
        )
        db_session.add(active_schedule)
        
        # Create inactive schedule with next_run_at (should NOT be in index)
        task_id2 = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id2}', '{user_id}', 'test2')
        """))
        await db_session.commit()
        
        inactive_schedule = TaskSchedule(
            task_template_id=task_id2,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 1 * * *",
            is_active=False,
            next_run_at=now,
        )
        db_session.add(inactive_schedule)
        
        # Create active schedule without next_run_at (should NOT be in index)
        task_id3 = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO tasks (id, user_id, task_type) 
            VALUES ('{task_id3}', '{user_id}', 'test3')
        """))
        await db_session.commit()
        
        no_next_run_schedule = TaskSchedule(
            task_template_id=task_id3,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 2 * * *",
            is_active=True,
            next_run_at=None,
        )
        db_session.add(no_next_run_schedule)
        
        await db_session.commit()
        
        # Query should use partial index for active schedules with next_run_at
        result = await db_session.execute(
            select(TaskSchedule).where(
                TaskSchedule.is_active == True,
                TaskSchedule.next_run_at != None,
            )
        )
        indexed_schedules = result.scalars().all()
        
        # Only the active schedule with next_run_at should be returned
        assert len(indexed_schedules) == 1
        assert indexed_schedules[0].id == active_schedule.id
    
    async def test_partial_index_exists(self, db_session: AsyncSession):
        """Test that the partial index exists with correct definition."""
        result = await db_session.execute(
            text("""
                SELECT indexdef 
                FROM pg_indexes 
                WHERE tablename = 'task_schedules' 
                AND indexname = 'idx_schedules_next_run'
            """)
        )
        index_def = result.scalar_one_or_none()
        
        assert index_def is not None
        assert 'WHERE is_active = true' in index_def or 'WHERE is_active' in index_def
        assert 'next_run_at' in index_def


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_task_schedule_create_validation(self):
        """Test TaskScheduleCreate model validation."""
        from db.models.task_schedule import TaskScheduleCreate
        
        task_id = gen_random_uuid()
        
        data = {
            "task_template_id": task_id,
            "schedule_type": ScheduleType.cron,
            "schedule_expression": "0 12 * * *",
            "is_active": True,
        }
        model = TaskScheduleCreate(**data)
        
        assert model.task_template_id == task_id
        assert model.schedule_type == ScheduleType.cron
        assert model.schedule_expression == "0 12 * * *"
        assert model.is_active is True
    
    def test_task_schedule_create_cron_validation(self):
        """Test cron expression validation in TaskScheduleCreate."""
        from db.models.task_schedule import TaskScheduleCreate
        from pydantic import ValidationError
        
        task_id = gen_random_uuid()
        
        # Valid cron expression
        data = {
            "task_template_id": task_id,
            "schedule_type": ScheduleType.cron,
            "schedule_expression": "*/15 * * * *",
        }
        model = TaskScheduleCreate(**data)
        assert model.schedule_expression == "*/15 * * * *"
        
        # Invalid cron expression
        data["schedule_expression"] = "invalid"
        with pytest.raises(ValidationError):
            TaskScheduleCreate(**data)
    
    def test_task_schedule_create_interval_validation(self):
        """Test interval expression validation in TaskScheduleCreate."""
        from db.models.task_schedule import TaskScheduleCreate
        from pydantic import ValidationError
        
        task_id = gen_random_uuid()
        
        # Valid interval
        data = {
            "task_template_id": task_id,
            "schedule_type": ScheduleType.interval,
            "schedule_expression": "PT30M",
        }
        model = TaskScheduleCreate(**data)
        assert model.schedule_expression == "PT30M"
        
        # Invalid interval
        data["schedule_expression"] = "every 30 minutes"
        with pytest.raises(ValidationError):
            TaskScheduleCreate(**data)
    
    def test_task_schedule_create_once_validation(self):
        """Test once expression validation in TaskScheduleCreate."""
        from db.models.task_schedule import TaskScheduleCreate
        from pydantic import ValidationError
        
        task_id = gen_random_uuid()
        
        # Valid timestamp
        data = {
            "task_template_id": task_id,
            "schedule_type": ScheduleType.once,
            "schedule_expression": "2026-03-22T15:00:00Z",
        }
        model = TaskScheduleCreate(**data)
        assert model.schedule_expression == "2026-03-22T15:00:00Z"
        
        # Invalid timestamp
        data["schedule_expression"] = "next tuesday"
        with pytest.raises(ValidationError):
            TaskScheduleCreate(**data)
    
    def test_schedule_type_string_coercion(self):
        """Test that string values are coerced to ScheduleType enum."""
        from db.models.task_schedule import TaskScheduleCreate
        
        task_id = gen_random_uuid()
        
        # Pass schedule_type as string - should be coerced
        data = {
            "task_template_id": task_id,
            "schedule_type": "interval",  # String, not enum
            "schedule_expression": "PT1H",
        }
        model = TaskScheduleCreate(**data)
        
        assert model.schedule_type == ScheduleType.interval
        assert isinstance(model.schedule_type, ScheduleType)
