# pyright: reportMissingImports=false
"""
Tests for TaskQueueDAO database operations.

This module tests CRUD operations for TaskQueueDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.

Import path: tests.db.test_task_queue_dao
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
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
from db.dto.task_queue_dto import TaskQueueCreate, TaskQueue, TaskQueueUpdate
from db.dao.task_queue_dao import TaskQueueDAO
from db.entity.task_queue_entity import TaskQueue as TaskQueueEntity
from db.entity.task_entity import Task as TaskEntity
from db.entity.user_entity import User as UserEntity
from db.entity.agent_entity import AgentType, AgentInstance
from db.entity.llm_endpoint_entity import LLMEndpoint, LLMEndpointGroup  # Required for UserEntity relationships
from db.types import TaskStatus


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
    """Clean all task_queue-related tables before and after tests."""
    # Clean before test
    await db_session.execute(delete(TaskQueueEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(AgentInstance))
    await db_session.execute(delete(AgentType))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    # Clean after test
    await db_session.rollback()
    await db_session.execute(delete(TaskQueueEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(AgentInstance))
    await db_session.execute(delete(AgentType))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, clean_data: None) -> UserEntity:
    """Create a test user for task ownership."""
    user = UserEntity(
        username="taskqueuetestuser",
        email="taskqueue_test@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_agent_type(db_session: AsyncSession, test_user: UserEntity) -> AgentType:
    """Create a test agent type."""
    agent_type = AgentType(
        name="TestQueueAgent",
        description="Test agent type for queue testing",
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


@pytest_asyncio.fixture
async def test_agent_instance(
    db_session: AsyncSession, 
    test_user: UserEntity, 
    test_agent_type: AgentType
) -> AgentInstance:
    """Create a test agent instance for claiming tasks."""
    agent_instance = AgentInstance(
        agent_type_id=test_agent_type.id,
        user_id=test_user.id,
        name="TestQueueAgentInstance",
        status="idle",
    )
    db_session.add(agent_instance)
    await db_session.commit()
    await db_session.refresh(agent_instance)
    return agent_instance


@pytest_asyncio.fixture
async def test_task(db_session: AsyncSession, test_user: UserEntity) -> TaskEntity:
    """Create a test task for queue entry."""
    task = TaskEntity(
        user_id=test_user.id,
        task_type="queue_test_task",
        status=TaskStatus.pending,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


# =============================================================================
# TaskQueue DAO Create Tests
# =============================================================================

class TestTaskQueueDAOCreate:
    """Test create operations for TaskQueueDAO."""
    
    async def test_create_queue_entry_minimal(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test creating a queue entry with minimal fields."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
        )
        
        created_queue = await TaskQueueDAO.create(queue_create, session=db_session)
        
        assert created_queue is not None
        assert created_queue.id is not None
        assert isinstance(created_queue.id, UUID)
        assert created_queue.task_id == test_task.id
        assert created_queue.status == TaskStatus.pending  # Default value
        assert created_queue.priority == 0  # Default value
        assert created_queue.retry_count == 0
        assert created_queue.max_retries == 3
        assert created_queue.queued_at is not None
        assert created_queue.created_at is not None
        assert created_queue.updated_at is not None
    
    async def test_create_queue_entry_with_all_fields(
        self, db_session: AsyncSession, test_task: TaskEntity, test_agent_instance: AgentInstance
    ):
        """Test creating a queue entry with all fields specified."""
        scheduled_time = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            status=TaskStatus.pending,
            priority=100,
            scheduled_at=scheduled_time,
            claimed_by=test_agent_instance.id,
            claimed_at=now,
            max_retries=5,
            result_json={"output": "test"},
        )
        
        created_queue = await TaskQueueDAO.create(queue_create, session=db_session)
        
        assert created_queue is not None
        assert created_queue.task_id == test_task.id
        assert created_queue.status == TaskStatus.pending
        assert created_queue.priority == 100
        assert created_queue.scheduled_at == scheduled_time
        assert created_queue.claimed_by == test_agent_instance.id
        assert created_queue.max_retries == 5
        assert created_queue.result_json == {"output": "test"}
    
    async def test_create_queue_entry_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that create returns a TaskQueue DTO, not an entity."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
        )
        
        created_queue = await TaskQueueDAO.create(queue_create, session=db_session)
        
        assert isinstance(created_queue, TaskQueue)
    
    async def test_create_multiple_queue_entries_for_different_tasks(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating multiple queue entries for different tasks."""
        # Create multiple tasks
        tasks = []
        for i in range(3):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"multi_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            tasks.append(task)
        
        # Create queue entries for each
        for i, task in enumerate(tasks):
            queue_create = TaskQueueCreate(
                task_id=task.id,
                priority=i * 10,
            )
            created = await TaskQueueDAO.create(queue_create, session=db_session)
            assert created.priority == i * 10


# =============================================================================
# TaskQueue DAO Get By Id Tests
# =============================================================================

class TestTaskQueueDAOGetById:
    """Test get_by_id operations for TaskQueueDAO."""
    
    async def test_get_by_id_returns_queue_entry(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test retrieving a queue entry by ID."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            priority=50,
        )
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        retrieved = await TaskQueueDAO.get_by_id(created.id, session=db_session)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.task_id == test_task.id
        assert retrieved.priority == 50
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        fake_id = uuid4()
        result = await TaskQueueDAO.get_by_id(fake_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that get_by_id returns a TaskQueue DTO."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        retrieved = await TaskQueueDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(retrieved, TaskQueue)


# =============================================================================
# TaskQueue DAO Get By Task Id Tests
# =============================================================================

class TestTaskQueueDAOGetByTaskId:
    """Test get_by_task_id operations for TaskQueueDAO."""
    
    async def test_get_by_task_id_returns_entry(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test retrieving a queue entry by task_id."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            priority=75,
        )
        await TaskQueueDAO.create(queue_create, session=db_session)
        
        entries = await TaskQueueDAO.get_by_task_id(test_task.id, session=db_session)
        
        assert len(entries) == 1
        assert entries[0].task_id == test_task.id
        assert entries[0].priority == 75
    
    async def test_get_by_task_id_nonexistent_returns_empty(
        self, db_session: AsyncSession
    ):
        """Test that get_by_task_id returns empty list for nonexistent task."""
        from uuid import uuid4
        
        fake_task_id = uuid4()
        result = await TaskQueueDAO.get_by_task_id(fake_task_id, session=db_session)
        
        assert result == []


# =============================================================================
# TaskQueue DAO Get By Claimed By Tests
# =============================================================================

class TestTaskQueueDAOGetByClaimedBy:
    """Test get_by_claimed_by operations for TaskQueueDAO."""
    
    async def test_get_by_claimed_by_returns_entries(
        self, db_session: AsyncSession, test_task: TaskEntity, test_agent_instance: AgentInstance
    ):
        """Test retrieving queue entries claimed by an agent."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            claimed_by=test_agent_instance.id,
            status=TaskStatus.running,
        )
        await TaskQueueDAO.create(queue_create, session=db_session)
        
        entries = await TaskQueueDAO.get_by_claimed_by(
            test_agent_instance.id, session=db_session
        )
        
        assert len(entries) == 1
        assert entries[0].claimed_by == test_agent_instance.id
    
    async def test_get_by_claimed_by_nonexistent_returns_empty(
        self, db_session: AsyncSession
    ):
        """Test that get_by_claimed_by returns empty list for nonexistent agent."""
        from uuid import uuid4
        
        fake_agent_id = uuid4()
        result = await TaskQueueDAO.get_by_claimed_by(fake_agent_id, session=db_session)
        
        assert result == []


# =============================================================================
# TaskQueue DAO Get All Tests
# =============================================================================

class TestTaskQueueDAOGetAll:
    """Test get_all operations for TaskQueueDAO."""
    
    async def test_get_all_returns_all_entries(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving all queue entries."""
        # Create multiple tasks and queue entries
        for i in range(5):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"getall_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            queue_create = TaskQueueCreate(task_id=task.id, priority=i)
            await TaskQueueDAO.create(queue_create, session=db_session)
        
        entries = await TaskQueueDAO.get_all(session=db_session)
        
        assert len(entries) == 5
    
    async def test_get_all_with_status_filter(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving queue entries with status filter."""
        # Create tasks with different statuses
        for i, status in enumerate([TaskStatus.pending, TaskStatus.running, TaskStatus.completed]):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"status_task_{i}",
                status=status,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            queue_create = TaskQueueCreate(task_id=task.id, status=status)
            await TaskQueueDAO.create(queue_create, session=db_session)
        
        pending_entries = await TaskQueueDAO.get_all(
            status=TaskStatus.pending, session=db_session
        )
        
        assert len(pending_entries) == 1
        assert pending_entries[0].status == TaskStatus.pending
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all pagination."""
        # Create 10 queue entries
        for i in range(10):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"page_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            queue_create = TaskQueueCreate(task_id=task.id)
            await TaskQueueDAO.create(queue_create, session=db_session)
        
        # Get first page
        page1 = await TaskQueueDAO.get_all(limit=5, offset=0, session=db_session)
        assert len(page1) == 5
        
        # Get second page
        page2 = await TaskQueueDAO.get_all(limit=5, offset=5, session=db_session)
        assert len(page2) == 5
        
        # Ensure no overlap
        page1_ids = {e.id for e in page1}
        page2_ids = {e.id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)


# =============================================================================
# TaskQueue DAO Update Tests
# =============================================================================

class TestTaskQueueDAOUpdate:
    """Test update operations for TaskQueueDAO."""
    
    async def test_update_status(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating queue entry status."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.running,
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.status == TaskStatus.running
    
    async def test_update_claimed_by_and_started_at(
        self, db_session: AsyncSession, test_task: TaskEntity, test_agent_instance: AgentInstance
    ):
        """Test updating claimed_by and started_at together."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        now = datetime.now(timezone.utc)
        update_dto = TaskQueueUpdate(
            id=created.id,
            claimed_by=test_agent_instance.id,
            claimed_at=now,
            started_at=now,
            status=TaskStatus.running,
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.claimed_by == test_agent_instance.id
        assert updated.status == TaskStatus.running
        assert updated.started_at is not None
    
    async def test_update_priority(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating queue entry priority."""
        queue_create = TaskQueueCreate(task_id=test_task.id, priority=10)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        update_dto = TaskQueueUpdate(id=created.id, priority=100)
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.priority == 100
    
    async def test_update_result_json(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating result_json field."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        result = {"output": "Task completed", "duration_ms": 5000}
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.completed,
            completed_at=datetime.now(timezone.utc),
            result_json=result,
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.result_json == result
        assert updated.status == TaskStatus.completed
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession
    ):
        """Test that updating nonexistent entry returns None."""
        from uuid import uuid4
        
        update_dto = TaskQueueUpdate(
            id=uuid4(),
            status=TaskStatus.running,
        )
        result = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert result is None
    
    async def test_update_partial_only_updates_provided_fields(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that partial updates only modify provided fields."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            priority=50,
            max_retries=5,
        )
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        # Only update status, not priority or max_retries
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.running,
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.status == TaskStatus.running
        assert updated.priority == 50  # Unchanged
        assert updated.max_retries == 5  # Unchanged


# =============================================================================
# TaskQueue DAO Delete Tests
# =============================================================================

class TestTaskQueueDAODelete:
    """Test delete operations for TaskQueueDAO."""
    
    async def test_delete_existing_entry(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test deleting an existing queue entry."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        deleted = await TaskQueueDAO.delete(created.id, session=db_session)
        
        assert deleted is True
        
        # Verify it's gone
        retrieved = await TaskQueueDAO.get_by_id(created.id, session=db_session)
        assert retrieved is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession
    ):
        """Test that deleting nonexistent entry returns False."""
        from uuid import uuid4
        
        result = await TaskQueueDAO.delete(uuid4(), session=db_session)
        
        assert result is False


# =============================================================================
# TaskQueue DAO Exists Tests
# =============================================================================

class TestTaskQueueDAOExists:
    """Test exists operations for TaskQueueDAO."""
    
    async def test_exists_returns_true_for_existing(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that exists returns True for existing entry."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        exists = await TaskQueueDAO.exists(created.id, session=db_session)
        
        assert exists is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession
    ):
        """Test that exists returns False for nonexistent entry."""
        from uuid import uuid4
        
        exists = await TaskQueueDAO.exists(uuid4(), session=db_session)
        
        assert exists is False


# =============================================================================
# TaskQueue DAO Count Tests
# =============================================================================

class TestTaskQueueDAOCount:
    """Test count operations for TaskQueueDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that count returns correct number of entries."""
        # Create 3 queue entries
        for i in range(3):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"count_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            queue_create = TaskQueueCreate(task_id=task.id)
            await TaskQueueDAO.create(queue_create, session=db_session)
        
        count = await TaskQueueDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_returns_zero(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that count returns 0 for empty table."""
        count = await TaskQueueDAO.count(session=db_session)
        
        assert count == 0


# =============================================================================
# TaskQueue DAO Priority Ordering Tests
# =============================================================================

class TestTaskQueueDAOPriorityOrdering:
    """Test priority ordering behavior."""
    
    async def test_get_all_returns_priority_ordered(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_all returns entries ordered by priority DESC."""
        # Create queue entries with different priorities
        priorities = [10, 50, 30, 20, 40]
        for i, priority in enumerate(priorities):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"priority_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            queue_create = TaskQueueCreate(task_id=task.id, priority=priority)
            await TaskQueueDAO.create(queue_create, session=db_session)
        
        # Get pending tasks (should be ordered by priority DESC)
        entries = await TaskQueueDAO.get_all(
            status=TaskStatus.pending, session=db_session
        )
        
        # Verify ordering (highest priority first)
        retrieved_priorities = [e.priority for e in entries]
        assert retrieved_priorities == sorted(priorities, reverse=True)


# =============================================================================
# TaskQueue DAO Retry Logic Tests
# =============================================================================

class TestTaskQueueDAORetryLogic:
    """Test retry logic operations."""
    
    async def test_update_retry_count(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating retry count."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            retry_count=0,
            max_retries=3,
        )
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        # Simulate retry
        update_dto = TaskQueueUpdate(
            id=created.id,
            retry_count=1,
            error_message="First attempt failed",
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.retry_count == 1
        assert updated.error_message == "First attempt failed"
    
    async def test_max_retries_configuration(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that max_retries can be configured per entry."""
        queue_create = TaskQueueCreate(
            task_id=test_task.id,
            max_retries=10,
        )
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        assert created.max_retries == 10


# =============================================================================
# TaskQueue DAO Status Transition Tests
# =============================================================================

class TestTaskQueueDAOStatusTransitions:
    """Test status transition workflows."""
    
    async def test_pending_to_running_transition(
        self, db_session: AsyncSession, test_task: TaskEntity, test_agent_instance: AgentInstance
    ):
        """Test transitioning from pending to running."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        now = datetime.now(timezone.utc)
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.running,
            claimed_by=test_agent_instance.id,
            claimed_at=now,
            started_at=now,
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated.status == TaskStatus.running
        assert updated.claimed_by == test_agent_instance.id
        assert updated.started_at is not None
    
    async def test_running_to_completed_transition(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test transitioning from running to completed."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        now = datetime.now(timezone.utc)
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.completed,
            completed_at=now,
            result_json={"output": "Success"},
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated.status == TaskStatus.completed
        assert updated.completed_at is not None
        assert updated.result_json == {"output": "Success"}
    
    async def test_running_to_failed_transition(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test transitioning from running to failed."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        now = datetime.now(timezone.utc)
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.failed,
            completed_at=now,
            error_message="Task failed due to timeout",
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated.status == TaskStatus.failed
        assert updated.error_message == "Task failed due to timeout"
    
    async def test_pending_to_cancelled_transition(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test transitioning from pending to cancelled."""
        queue_create = TaskQueueCreate(task_id=test_task.id)
        created = await TaskQueueDAO.create(queue_create, session=db_session)
        
        now = datetime.now(timezone.utc)
        update_dto = TaskQueueUpdate(
            id=created.id,
            status=TaskStatus.cancelled,
            completed_at=now,
        )
        updated = await TaskQueueDAO.update(update_dto, session=db_session)
        
        assert updated.status == TaskStatus.cancelled
        assert updated.completed_at is not None