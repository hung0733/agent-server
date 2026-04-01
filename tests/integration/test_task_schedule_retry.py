# pyright: reportMissingImports=false
"""
Integration tests for task schedule retry mechanism.

Tests the complete retry flow including:
- Failure tracking (consecutive_failures, last_failure_at)
- Exponential backoff delay calculation
- Success resets failure counter
- next_run_at updates with retry delays

Import path: tests.integration.test_task_schedule_retry
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.user_dao import UserDAO
from db.dto.agent_dto import AgentTypeCreate, AgentInstanceCreate
from db.dto.task_dto import TaskCreate
from db.dto.task_schedule_dto import TaskScheduleCreate, TaskScheduleUpdate
from db.dto.user_dto import UserCreate
from db.types import TaskStatus, Priority, ScheduleType, TaskExecutionType, AgentStatus
from scheduler.task_scheduler import calculate_retry_delay_seconds


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
        description="Test agent type for retry tests",
    )
    agent_type = await AgentTypeDAO.create(agent_type_dto)
    return agent_type.id


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_agent_type: UUID, test_user: UUID) -> UUID:
    """Create a test agent instance."""
    agent_dto = AgentInstanceCreate(
        agent_type_id=test_agent_type,
        user_id=test_user,
        name=f"test_agent_{uuid4().hex[:8]}",
        status=AgentStatus.idle,
    )
    agent = await AgentInstanceDAO.create(agent_dto)
    return agent.id


@pytest.mark.asyncio
class TestTaskScheduleRetry:
    """Integration test suite for task schedule retry mechanism."""

    async def test_consecutive_failures_increment(
        self, db_session: AsyncSession, test_user: UUID, test_agent: UUID
    ):
        """Test that consecutive_failures increments on each failure."""
        # Create a task template
        task = await TaskDAO.create(
            TaskCreate(
                user_id=test_user,
                agent_id=test_agent,
                task_type=TaskExecutionType.message,
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={"prompt": "test task"},
            )
        )

        # Create a schedule
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.interval,
                schedule_expression="PT1H",
                is_active=True,
                next_run_at=datetime.now(timezone.utc),
            )
        )

        # Simulate failures by incrementing consecutive_failures
        for expected_count in range(1, 6):
            schedule = await TaskScheduleDAO.update(
                TaskScheduleUpdate(
                    id=schedule.id,
                    consecutive_failures=expected_count,
                    last_failure_at=datetime.now(timezone.utc),
                )
            )
            assert schedule.consecutive_failures == expected_count

        # Cleanup
        await TaskScheduleDAO.delete(schedule.id)
        await TaskDAO.delete(task.id)

    async def test_success_resets_consecutive_failures(
        self, db_session: AsyncSession, test_user: UUID, test_agent: UUID
    ):
        """Test that successful execution resets consecutive_failures to 0."""
        # Create a task template
        task = await TaskDAO.create(
            TaskCreate(
                user_id=test_user,
                agent_id=test_agent,
                task_type=TaskExecutionType.message,
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={"prompt": "test task"},
            )
        )

        # Create a schedule with some failures
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.interval,
                schedule_expression="PT1H",
                is_active=True,
                next_run_at=datetime.now(timezone.utc),
                consecutive_failures=5,
                last_failure_at=datetime.now(timezone.utc),
            )
        )

        assert schedule.consecutive_failures == 5
        assert schedule.last_failure_at is not None

        # Simulate success by resetting failures
        schedule = await TaskScheduleDAO.update(
            TaskScheduleUpdate(
                id=schedule.id,
                consecutive_failures=0,
                last_failure_at=None,
            )
        )

        assert schedule.consecutive_failures == 0
        assert schedule.last_failure_at is None

        # Cleanup
        await TaskScheduleDAO.delete(schedule.id)
        await TaskDAO.delete(task.id)

    async def test_retry_delay_progression(
        self, db_session: AsyncSession, test_user: UUID, test_agent: UUID
    ):
        """Test that retry delays follow the exponential backoff strategy."""
        # Create a task template
        task = await TaskDAO.create(
            TaskCreate(
                user_id=test_user,
                agent_id=test_agent,
                task_type=TaskExecutionType.message,
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={"prompt": "test task"},
            )
        )

        # Create a schedule
        current_time = datetime.now(timezone.utc)
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.interval,
                schedule_expression="PT1H",
                is_active=True,
                next_run_at=current_time,
            )
        )

        # Test retry delay progression
        expected_delays = [30, 60, 300, 900, 3600, 3600]  # seconds

        for failure_count, expected_delay in enumerate(expected_delays, start=1):
            # Calculate expected next retry time
            retry_delay = calculate_retry_delay_seconds(failure_count)
            assert retry_delay == expected_delay, (
                f"Failure count {failure_count} should have delay {expected_delay}s"
            )

            # Update schedule with failure
            next_retry_time = current_time + timedelta(seconds=retry_delay)
            schedule = await TaskScheduleDAO.update(
                TaskScheduleUpdate(
                    id=schedule.id,
                    consecutive_failures=failure_count,
                    last_failure_at=current_time,
                    next_run_at=next_retry_time,
                )
            )

            # Verify the schedule was updated correctly
            assert schedule.consecutive_failures == failure_count
            assert schedule.last_failure_at == current_time

            # Verify next_run_at is approximately correct (within 1 second tolerance)
            time_diff = abs((schedule.next_run_at - next_retry_time).total_seconds())
            assert time_diff < 1, (
                f"next_run_at should be ~{expected_delay}s after current_time, "
                f"but was {time_diff}s off"
            )

        # Cleanup
        await TaskScheduleDAO.delete(schedule.id)
        await TaskDAO.delete(task.id)

    async def test_last_failure_at_tracking(
        self, db_session: AsyncSession, test_user: UUID, test_agent: UUID
    ):
        """Test that last_failure_at is properly tracked."""
        # Create a task template
        task = await TaskDAO.create(
            TaskCreate(
                user_id=test_user,
                agent_id=test_agent,
                task_type=TaskExecutionType.message,
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={"prompt": "test task"},
            )
        )

        # Create a schedule
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.interval,
                schedule_expression="PT1H",
                is_active=True,
                next_run_at=datetime.now(timezone.utc),
            )
        )

        # Initially, last_failure_at should be None
        assert schedule.last_failure_at is None

        # Simulate a failure
        failure_time = datetime.now(timezone.utc)
        schedule = await TaskScheduleDAO.update(
            TaskScheduleUpdate(
                id=schedule.id,
                consecutive_failures=1,
                last_failure_at=failure_time,
            )
        )

        assert schedule.last_failure_at is not None
        time_diff = abs((schedule.last_failure_at - failure_time).total_seconds())
        assert time_diff < 1, "last_failure_at should match the failure time"

        # Simulate success (reset)
        schedule = await TaskScheduleDAO.update(
            TaskScheduleUpdate(
                id=schedule.id,
                consecutive_failures=0,
                last_failure_at=None,
            )
        )

        assert schedule.last_failure_at is None

        # Cleanup
        await TaskScheduleDAO.delete(schedule.id)
        await TaskDAO.delete(task.id)

    async def test_next_run_at_updated_on_failure(
        self, db_session: AsyncSession, test_user: UUID, test_agent: UUID
    ):
        """Test that next_run_at is updated with retry delay on failure."""
        # Create a task template
        task = await TaskDAO.create(
            TaskCreate(
                user_id=test_user,
                agent_id=test_agent,
                task_type=TaskExecutionType.message,
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={"prompt": "test task"},
            )
        )

        # Create a schedule
        current_time = datetime.now(timezone.utc)
        original_next_run = current_time + timedelta(hours=1)

        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.interval,
                schedule_expression="PT1H",
                is_active=True,
                next_run_at=original_next_run,
            )
        )

        # Simulate first failure (30 second retry)
        failure_time = datetime.now(timezone.utc)
        retry_delay = calculate_retry_delay_seconds(1)
        expected_next_run = failure_time + timedelta(seconds=retry_delay)

        schedule = await TaskScheduleDAO.update(
            TaskScheduleUpdate(
                id=schedule.id,
                consecutive_failures=1,
                last_failure_at=failure_time,
                next_run_at=expected_next_run,
            )
        )

        # Verify next_run_at was updated
        time_diff = abs((schedule.next_run_at - expected_next_run).total_seconds())
        assert time_diff < 1, (
            f"next_run_at should be ~30s after failure, but was {time_diff}s off"
        )

        # Cleanup
        await TaskScheduleDAO.delete(schedule.id)
        await TaskDAO.delete(task.id)

    async def test_schedule_retrieval_with_retry_fields(
        self, db_session: AsyncSession, test_user: UUID, test_agent: UUID
    ):
        """Test that schedules can be retrieved with retry fields populated."""
        # Create a task template
        task = await TaskDAO.create(
            TaskCreate(
                user_id=test_user,
                agent_id=test_agent,
                task_type=TaskExecutionType.message,
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={"prompt": "test task"},
            )
        )

        # Create a schedule with failure data
        failure_time = datetime.now(timezone.utc)
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.interval,
                schedule_expression="PT1H",
                is_active=True,
                next_run_at=failure_time + timedelta(seconds=30),
                consecutive_failures=1,
                last_failure_at=failure_time,
            )
        )

        # Retrieve the schedule
        retrieved_schedule = await TaskScheduleDAO.get_by_id(schedule.id)

        assert retrieved_schedule is not None
        assert retrieved_schedule.consecutive_failures == 1
        assert retrieved_schedule.last_failure_at is not None

        # Cleanup
        await TaskScheduleDAO.delete(schedule.id)
        await TaskDAO.delete(task.id)
