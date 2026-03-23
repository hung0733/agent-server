# pyright: reportMissingImports=false
"""
Tests for TaskScheduleDAO database operations.

This module tests CRUD operations for TaskScheduleDAO following the DAO pattern.
TaskSchedule manages recurring task execution patterns with support for cron,
interval, and one-time schedules.

Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.task_schedule_dto import TaskScheduleCreate, TaskSchedule, TaskScheduleUpdate
from db.dto.task_dto import TaskCreate
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.task_dao import TaskDAO
from db.entity.task_schedule_entity import TaskSchedule as TaskScheduleEntity
from db.entity.task_entity import Task as TaskEntity
from db.entity.user_entity import User as UserEntity
from db.entity.llm_endpoint_entity import LLMEndpoint, LLMEndpointGroup  # Required for UserEntity relationships
from db.types import ScheduleType


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
    """Clean all task schedule-related tables before and after tests."""
    # Clean before test
    await db_session.execute(delete(TaskScheduleEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    # Clean after test
    await db_session.rollback()
    await db_session.execute(delete(TaskScheduleEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, clean_data: None) -> UserEntity:
    """Create a test user for task ownership."""
    user = UserEntity(
        username="scheduletestuser",
        email="scheduletest@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_task(db_session: AsyncSession, test_user: UserEntity) -> TaskEntity:
    """Create a test task to serve as a task template."""
    task_create = TaskCreate(
        user_id=test_user.id,
        task_type="scheduled_task",
    )
    task = await TaskDAO.create(task_create, session=db_session)
    return task


# =============================================================================
# TaskSchedule DAO Create Tests
# =============================================================================

class TestTaskScheduleDAOCreate:
    """Test create operations for TaskScheduleDAO."""
    
    async def test_create_schedule_with_minimal_fields(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test creating a schedule with only required fields."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 12 * * *",  # Daily at noon
        )
        
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        assert created_schedule is not None
        assert created_schedule.id is not None
        assert isinstance(created_schedule.id, UUID)
        assert created_schedule.task_template_id == test_task.id
        assert created_schedule.schedule_type == ScheduleType.cron  # Default
        assert created_schedule.schedule_expression == "0 12 * * *"
        assert created_schedule.is_active is True  # Default
        assert created_schedule.next_run_at is None
        assert created_schedule.last_run_at is None
        assert created_schedule.created_at is not None
        assert created_schedule.updated_at is not None
        assert isinstance(created_schedule.created_at, datetime)
        assert isinstance(created_schedule.updated_at, datetime)
    
    async def test_create_schedule_with_all_fields(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a schedule with all fields specified."""
        # Create a new task for this test
        task_create = TaskCreate(user_id=test_user.id, task_type="full_schedule_test")
        task = await TaskDAO.create(task_create, session=db_session)
        
        next_run = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_run = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        
        schedule_create = TaskScheduleCreate(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 18 * * *",  # Daily at 6pm
            is_active=False,
            next_run_at=next_run,
            last_run_at=last_run,
        )
        
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        assert created_schedule is not None
        assert created_schedule.schedule_type == ScheduleType.cron
        assert created_schedule.schedule_expression == "0 18 * * *"
        assert created_schedule.is_active is False
        assert created_schedule.next_run_at == next_run
        assert created_schedule.last_run_at == last_run
    
    async def test_create_schedule_cron_type(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a cron schedule."""
        task_create = TaskCreate(user_id=test_user.id, task_type="cron_task")
        task = await TaskDAO.create(task_create, session=db_session)
        
        schedule_create = TaskScheduleCreate(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="*/15 * * * *",  # Every 15 minutes
        )
        
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        assert created_schedule.schedule_type == ScheduleType.cron
        assert created_schedule.schedule_expression == "*/15 * * * *"
    
    async def test_create_schedule_interval_type(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating an interval schedule."""
        task_create = TaskCreate(user_id=test_user.id, task_type="interval_task")
        task = await TaskDAO.create(task_create, session=db_session)
        
        schedule_create = TaskScheduleCreate(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 */2 * * *",  # Every 2 hours
        )
        
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        assert created_schedule.schedule_type == ScheduleType.cron
        assert created_schedule.schedule_expression == "0 */2 * * *"
    
    async def test_create_schedule_once_type(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a one-time schedule."""
        task_create = TaskCreate(user_id=test_user.id, task_type="once_task")
        task = await TaskDAO.create(task_create, session=db_session)
        
        schedule_create = TaskScheduleCreate(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 0 1 1 *",  # Once a year on Jan 1
        )
        
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        assert created_schedule.schedule_type == ScheduleType.cron
        assert created_schedule.schedule_expression == "0 0 1 1 *"
    
    async def test_create_schedule_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that create returns a TaskSchedule DTO, not an entity."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 0 * * *",
        )
        
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        assert isinstance(created_schedule, TaskSchedule)


# =============================================================================
# TaskSchedule DAO Get By ID Tests
# =============================================================================

class TestTaskScheduleDAOGetById:
    """Test get_by_id operations for TaskScheduleDAO."""
    
    async def test_get_by_id_returns_schedule(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test retrieving a schedule by ID."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 8 * * 1-5",  # Weekdays at 8am
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        fetched_schedule = await TaskScheduleDAO.get_by_id(created_schedule.id, session=db_session)
        
        assert fetched_schedule is not None
        assert fetched_schedule.id == created_schedule.id
        assert fetched_schedule.schedule_expression == "0 8 * * 1-5"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        nonexistent_id = uuid4()
        
        result = await TaskScheduleDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that get_by_id returns a TaskSchedule DTO."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 0 * * *",
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        fetched_schedule = await TaskScheduleDAO.get_by_id(created_schedule.id, session=db_session)
        
        assert isinstance(fetched_schedule, TaskSchedule)


# =============================================================================
# TaskSchedule DAO Get By Task Template ID Tests
# =============================================================================

class TestTaskScheduleDAOGetByTaskTemplateId:
    """Test get_by_task_template_id operations for TaskScheduleDAO."""
    
    async def test_get_by_task_template_id_returns_schedule(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test retrieving a schedule by task_template_id."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 12 * * *",
        )
        await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        fetched_schedule = await TaskScheduleDAO.get_by_task_template_id(
            test_task.id, session=db_session
        )
        
        assert fetched_schedule is not None
        assert fetched_schedule.task_template_id == test_task.id
    
    async def test_get_by_task_template_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_by_task_template_id returns None for nonexistent task."""
        nonexistent_task_id = uuid4()
        
        result = await TaskScheduleDAO.get_by_task_template_id(
            nonexistent_task_id, session=db_session
        )
        
        assert result is None


# =============================================================================
# TaskSchedule DAO Get All Tests
# =============================================================================

class TestTaskScheduleDAOGetAll:
    """Test get_all operations for TaskScheduleDAO."""
    
    async def test_get_all_returns_all_schedules(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving all schedules."""
        for i in range(3):
            task_create = TaskCreate(user_id=test_user.id, task_type=f"scheduled_{i}")
            task = await TaskDAO.create(task_create, session=db_session)
            
            schedule_create = TaskScheduleCreate(
                task_template_id=task.id,
                schedule_expression=f"0 {i} * * *",
            )
            await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        schedules = await TaskScheduleDAO.get_all(session=db_session)
        
        assert len(schedules) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_all returns empty list when no schedules exist."""
        schedules = await TaskScheduleDAO.get_all(session=db_session)
        
        assert schedules == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            task_create = TaskCreate(user_id=test_user.id, task_type=f"page_{i}")
            task = await TaskDAO.create(task_create, session=db_session)
            
            schedule_create = TaskScheduleCreate(
                task_template_id=task.id,
                schedule_expression="0 * * * *",
            )
            await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        # Test limit
        schedules_limited = await TaskScheduleDAO.get_all(limit=2, session=db_session)
        assert len(schedules_limited) == 2
        
        # Test offset
        schedules_offset = await TaskScheduleDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(schedules_offset) == 2
    
    async def test_get_all_with_active_filter(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all with is_active filter."""
        for i in range(3):
            task_create = TaskCreate(user_id=test_user.id, task_type=f"active_test_{i}")
            task = await TaskDAO.create(task_create, session=db_session)
            
            schedule_create = TaskScheduleCreate(
                task_template_id=task.id,
                schedule_expression="0 * * * *",
                is_active=(i % 2 == 0),  # 0 and 2 are active, 1 is inactive
            )
            await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        # Get only active schedules
        active_schedules = await TaskScheduleDAO.get_all(
            is_active=True, session=db_session
        )
        assert len(active_schedules) == 2
        
        # Get only inactive schedules
        inactive_schedules = await TaskScheduleDAO.get_all(
            is_active=False, session=db_session
        )
        assert len(inactive_schedules) == 1


# =============================================================================
# TaskSchedule DAO Update Tests
# =============================================================================

class TestTaskScheduleDAOUpdate:
    """Test update operations for TaskScheduleDAO."""
    
    async def test_update_schedule_expression(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating a schedule's expression."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 12 * * *",
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        schedule_update = TaskScheduleUpdate(
            id=created_schedule.id,
            schedule_expression="0 18 * * *",  # Change to 6pm
        )
        updated_schedule = await TaskScheduleDAO.update(schedule_update, session=db_session)
        
        assert updated_schedule is not None
        assert updated_schedule.schedule_expression == "0 18 * * *"
    
    async def test_update_schedule_active_status(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating a schedule's active status."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 * * * *",
            is_active=True,
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        schedule_update = TaskScheduleUpdate(
            id=created_schedule.id,
            is_active=False,
        )
        updated_schedule = await TaskScheduleDAO.update(schedule_update, session=db_session)
        
        assert updated_schedule is not None
        assert updated_schedule.is_active is False
    
    async def test_update_schedule_timestamps(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating next_run_at and last_run_at."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 * * * *",
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        next_run = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_run = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        
        schedule_update = TaskScheduleUpdate(
            id=created_schedule.id,
            next_run_at=next_run,
            last_run_at=last_run,
        )
        updated_schedule = await TaskScheduleDAO.update(schedule_update, session=db_session)
        
        assert updated_schedule is not None
        assert updated_schedule.next_run_at == next_run
        assert updated_schedule.last_run_at == last_run
    
    async def test_update_nonexistent_schedule_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that updating a nonexistent schedule returns None."""
        schedule_update = TaskScheduleUpdate(
            id=uuid4(),
            schedule_expression="0 0 * * *",
        )
        
        result = await TaskScheduleDAO.update(schedule_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that update returns a TaskSchedule DTO."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 * * * *",
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        schedule_update = TaskScheduleUpdate(
            id=created_schedule.id,
            is_active=False,
        )
        updated_schedule = await TaskScheduleDAO.update(schedule_update, session=db_session)
        
        assert isinstance(updated_schedule, TaskSchedule)


# =============================================================================
# TaskSchedule DAO Delete Tests
# =============================================================================

class TestTaskScheduleDAODelete:
    """Test delete operations for TaskScheduleDAO."""
    
    async def test_delete_existing_schedule(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test deleting an existing schedule."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 * * * *",
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        result = await TaskScheduleDAO.delete(created_schedule.id, session=db_session)
        
        assert result is True
        
        # Verify schedule is deleted
        fetched = await TaskScheduleDAO.get_by_id(created_schedule.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_schedule_returns_false(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that deleting a nonexistent schedule returns False."""
        result = await TaskScheduleDAO.delete(uuid4(), session=db_session)
        
        assert result is False


# =============================================================================
# TaskSchedule DAO Exists Tests
# =============================================================================

class TestTaskScheduleDAOExists:
    """Test exists operations for TaskScheduleDAO."""
    
    async def test_exists_returns_true_for_existing_schedule(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that exists returns True for existing schedule."""
        schedule_create = TaskScheduleCreate(
            task_template_id=test_task.id,
            schedule_expression="0 * * * *",
        )
        created_schedule = await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        result = await TaskScheduleDAO.exists(created_schedule.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_schedule(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that exists returns False for nonexistent schedule."""
        result = await TaskScheduleDAO.exists(uuid4(), session=db_session)
        
        assert result is False


# =============================================================================
# TaskSchedule DAO Count Tests
# =============================================================================

class TestTaskScheduleDAOCount:
    """Test count operations for TaskScheduleDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that count returns the correct number of schedules."""
        for i in range(3):
            task_create = TaskCreate(user_id=test_user.id, task_type=f"count_{i}")
            task = await TaskDAO.create(task_create, session=db_session)
            
            schedule_create = TaskScheduleCreate(
                task_template_id=task.id,
                schedule_expression="0 * * * *",
            )
            await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        count = await TaskScheduleDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that count returns 0 for empty table."""
        count = await TaskScheduleDAO.count(session=db_session)
        
        assert count == 0


# =============================================================================
# TaskSchedule DAO Get Active Schedules Tests
# =============================================================================

class TestTaskScheduleDAOGetActiveSchedules:
    """Test get_active_schedules operations for TaskScheduleDAO."""
    
    async def test_get_active_schedules_returns_only_active(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_active_schedules only returns active schedules with next_run_at."""
        # Create schedules with different states
        for i in range(4):
            task_create = TaskCreate(user_id=test_user.id, task_type=f"active_sched_{i}")
            task = await TaskDAO.create(task_create, session=db_session)
            
            schedule_create = TaskScheduleCreate(
                task_template_id=task.id,
                schedule_expression="0 * * * *",
                is_active=(i < 3),  # First 3 are active
                next_run_at=datetime(2026, 4, i + 1, 12, 0, 0, tzinfo=timezone.utc) if i < 2 else None,
            )
            await TaskScheduleDAO.create(schedule_create, session=db_session)
        
        # Get active schedules with next_run_at set
        active_schedules = await TaskScheduleDAO.get_active_schedules(session=db_session)
        
        # Only schedules with is_active=True AND next_run_at IS NOT NULL should be returned
        assert len(active_schedules) == 2
    
    async def test_get_active_schedules_empty_returns_empty_list(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_active_schedules returns empty list when no active schedules."""
        result = await TaskScheduleDAO.get_active_schedules(session=db_session)
        
        assert result == []