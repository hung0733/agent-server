# pyright: reportMissingImports=false
"""
Tests for DeadLetterQueueDAO database operations.

This module tests CRUD operations for DeadLetterQueueDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.

Import path: tests.db.test_dead_letter_queue_dao
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
from db.dto.dead_letter_queue_dto import (
    DeadLetterQueueCreate,
    DeadLetterQueue,
    DeadLetterQueueUpdate,
)
from db.dao.dead_letter_queue_dao import DeadLetterQueueDAO
from db.entity.dead_letter_queue_entity import DeadLetterQueue as DeadLetterQueueEntity
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
    """Clean all dead_letter_queue-related tables before and after tests."""
    # Clean before test (order matters due to FK constraints)
    await db_session.execute(delete(DeadLetterQueueEntity))
    await db_session.execute(delete(TaskQueueEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(AgentInstance))
    await db_session.execute(delete(AgentType))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    # Clean after test
    await db_session.rollback()
    await db_session.execute(delete(DeadLetterQueueEntity))
    await db_session.execute(delete(TaskQueueEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(AgentInstance))
    await db_session.execute(delete(AgentType))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, clean_data: None) -> UserEntity:
    """Create a test user for ownership."""
    user = UserEntity(
        username="dlqtestuser",
        email="dlq_test@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_agent_type(db_session: AsyncSession, test_user: UserEntity) -> AgentType:
    """Create a test agent type."""
    agent_type = AgentType(
        name="TestDLQAgent",
        description="Test agent type for DLQ testing",
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
    """Create a test agent instance."""
    agent_instance = AgentInstance(
        agent_type_id=test_agent_type.id,
        user_id=test_user.id,
        name="TestDLQAgentInstance",
        status="idle",
    )
    db_session.add(agent_instance)
    await db_session.commit()
    await db_session.refresh(agent_instance)
    return agent_instance


@pytest_asyncio.fixture
async def test_task(db_session: AsyncSession, test_user: UserEntity) -> TaskEntity:
    """Create a test task."""
    task = TaskEntity(
        user_id=test_user.id,
        task_type="dlq_test_task",
        status=TaskStatus.failed,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest_asyncio.fixture
async def test_queue_entry(
    db_session: AsyncSession, 
    test_task: TaskEntity
) -> TaskQueueEntity:
    """Create a test queue entry."""
    queue_entry = TaskQueueEntity(
        task_id=test_task.id,
        status=TaskStatus.failed,
    )
    db_session.add(queue_entry)
    await db_session.commit()
    await db_session.refresh(queue_entry)
    return queue_entry


# =============================================================================
# DeadLetterQueue DAO Create Tests
# =============================================================================

class TestDeadLetterQueueDAOCreate:
    """Test create operations for DeadLetterQueueDAO."""
    
    async def test_create_dlq_entry_minimal(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test creating a DLQ entry with minimal required fields."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="MaxRetriesExceeded",
            failure_details_json={"error": "test error", "attempts": 3},
        )
        
        created_dlq = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert created_dlq is not None
        assert created_dlq.id is not None
        assert isinstance(created_dlq.id, UUID)
        assert created_dlq.original_task_id == test_task.id
        assert created_dlq.failure_reason == "MaxRetriesExceeded"
        assert created_dlq.retry_count == 0  # Default value
        assert created_dlq.is_active is True  # Default value
        assert created_dlq.resolved_at is None
        assert created_dlq.resolved_by is None
        assert created_dlq.dead_lettered_at is not None
        assert created_dlq.created_at is not None
        assert created_dlq.updated_at is not None
    
    async def test_create_dlq_entry_with_all_fields(
        self, db_session: AsyncSession, 
        test_task: TaskEntity, 
        test_queue_entry: TaskQueueEntity,
        test_user: UserEntity
    ):
        """Test creating a DLQ entry with all fields specified."""
        now = datetime.now(timezone.utc)
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_queue_entry_id=test_queue_entry.id,
            original_payload_json={
                "task_id": str(test_task.id),
                "task_type": "research",
                "payload": {"query": "test"},
            },
            failure_reason="ConnectionTimeout",
            failure_details_json={
                "error": "Connection timed out after 30s",
                "stack_trace": "File 'app.py', line 42",
                "retry_attempts": 3,
            },
            retry_count=3,
            last_attempt_at=now,
            is_active=True,
        )
        
        created_dlq = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert created_dlq is not None
        assert created_dlq.original_task_id == test_task.id
        assert created_dlq.original_queue_entry_id == test_queue_entry.id
        assert created_dlq.failure_reason == "ConnectionTimeout"
        assert created_dlq.retry_count == 3
        assert created_dlq.last_attempt_at is not None
        assert created_dlq.original_payload_json["task_type"] == "research"
        assert "stack_trace" in created_dlq.failure_details_json
    
    async def test_create_dlq_entry_without_task_id(
        self, db_session: AsyncSession
    ):
        """Test creating a DLQ entry without original_task_id (allowed - SET NULL FK)."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=None,
            original_payload_json={"task": "orphan"},
            failure_reason="OrphanedTask",
            failure_details_json={"error": "no task reference"},
        )
        
        created_dlq = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert created_dlq is not None
        assert created_dlq.original_task_id is None
    
    async def test_create_dlq_entry_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that create returns a DeadLetterQueue DTO, not an entity."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        
        created_dlq = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert isinstance(created_dlq, DeadLetterQueue)
    
    async def test_create_multiple_dlq_entries(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating multiple DLQ entries."""
        for i in range(3):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"multi_dlq_task_{i}",
                status=TaskStatus.failed,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            dlq_create = DeadLetterQueueCreate(
                original_task_id=task.id,
                original_payload_json={"task": f"task_{i}"},
                failure_reason=f"Failure{i}",
                failure_details_json={"error": f"error_{i}"},
                retry_count=i,
            )
            created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
            assert created.retry_count == i


# =============================================================================
# DeadLetterQueue DAO Get By Id Tests
# =============================================================================

class TestDeadLetterQueueDAOGetById:
    """Test get_by_id operations for DeadLetterQueueDAO."""
    
    async def test_get_by_id_returns_dlq_entry(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test retrieving a DLQ entry by ID."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        retrieved = await DeadLetterQueueDAO.get_by_id(created.id, session=db_session)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.original_task_id == test_task.id
        assert retrieved.failure_reason == "TestFailure"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        fake_id = uuid4()
        result = await DeadLetterQueueDAO.get_by_id(fake_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that get_by_id returns a DeadLetterQueue DTO."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        retrieved = await DeadLetterQueueDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(retrieved, DeadLetterQueue)


# =============================================================================
# DeadLetterQueue DAO Get By Original Task Id Tests
# =============================================================================

class TestDeadLetterQueueDAOGetByOriginalTaskId:
    """Test get_by_original_task_id operations for DeadLetterQueueDAO."""
    
    async def test_get_by_original_task_id_returns_entry(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test retrieving a DLQ entry by original_task_id."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        entries = await DeadLetterQueueDAO.get_by_original_task_id(
            test_task.id, session=db_session
        )
        
        assert len(entries) == 1
        assert entries[0].original_task_id == test_task.id
    
    async def test_get_by_original_task_id_nonexistent_returns_empty(
        self, db_session: AsyncSession
    ):
        """Test that get_by_original_task_id returns empty list for nonexistent task."""
        from uuid import uuid4
        
        fake_task_id = uuid4()
        result = await DeadLetterQueueDAO.get_by_original_task_id(
            fake_task_id, session=db_session
        )
        
        assert result == []


# =============================================================================
# DeadLetterQueue DAO Get All Tests
# =============================================================================

class TestDeadLetterQueueDAOGetAll:
    """Test get_all operations for DeadLetterQueueDAO."""
    
    async def test_get_all_returns_all_entries(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving all DLQ entries."""
        # Create multiple tasks and DLQ entries
        for i in range(5):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"getall_task_{i}",
                status=TaskStatus.failed,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            dlq_create = DeadLetterQueueCreate(
                original_task_id=task.id,
                original_payload_json={"task": f"task_{i}"},
                failure_reason=f"Failure{i}",
                failure_details_json={"error": f"error_{i}"},
            )
            await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        entries = await DeadLetterQueueDAO.get_all(session=db_session)
        
        assert len(entries) == 5
    
    async def test_get_all_with_is_active_filter(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving DLQ entries with is_active filter."""
        for i in range(4):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"active_task_{i}",
                status=TaskStatus.failed,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            dlq_create = DeadLetterQueueCreate(
                original_task_id=task.id,
                original_payload_json={"task": f"task_{i}"},
                failure_reason=f"Failure{i}",
                failure_details_json={"error": "test"},
                is_active=(i < 2),  # First 2 active, last 2 inactive
            )
            await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        active_entries = await DeadLetterQueueDAO.get_all(
            is_active=True, session=db_session
        )
        
        assert len(active_entries) == 2
        for entry in active_entries:
            assert entry.is_active is True
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all pagination."""
        # Create 10 DLQ entries
        for i in range(10):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"page_task_{i}",
                status=TaskStatus.failed,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            dlq_create = DeadLetterQueueCreate(
                original_task_id=task.id,
                original_payload_json={"task": f"task_{i}"},
                failure_reason=f"Failure{i}",
                failure_details_json={"error": "test"},
            )
            await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        # Get first page
        page1 = await DeadLetterQueueDAO.get_all(limit=5, offset=0, session=db_session)
        assert len(page1) == 5
        
        # Get second page
        page2 = await DeadLetterQueueDAO.get_all(limit=5, offset=5, session=db_session)
        assert len(page2) == 5
        
        # Ensure no overlap
        page1_ids = {e.id for e in page1}
        page2_ids = {e.id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)


# =============================================================================
# DeadLetterQueue DAO Update Tests
# =============================================================================

class TestDeadLetterQueueDAOUpdate:
    """Test update operations for DeadLetterQueueDAO."""
    
    async def test_update_failure_reason(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating DLQ entry failure_reason."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="InitialFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            failure_reason="UpdatedFailure",
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.failure_reason == "UpdatedFailure"
    
    async def test_update_resolve_dlq_entry(
        self, db_session: AsyncSession, test_task: TaskEntity, test_user: UserEntity
    ):
        """Test resolving a DLQ entry (admin workflow)."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            is_active=True,
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        # Resolve the DLQ entry
        now = datetime.now(timezone.utc)
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            is_active=False,
            resolved_at=now,
            resolved_by=test_user.id,
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.is_active is False
        assert updated.resolved_at is not None
        assert updated.resolved_by == test_user.id
    
    async def test_update_retry_count(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating retry count."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            retry_count=1,
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            retry_count=3,
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.retry_count == 3
    
    async def test_update_failure_details_json(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test updating failure_details_json field."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "initial"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        new_details = {
            "error": "Updated error",
            "stack_trace": "File 'app.py', line 100",
            "additional_info": {"retry_attempts": 5},
        }
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            failure_details_json=new_details,
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.failure_details_json == new_details
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession
    ):
        """Test that updating nonexistent entry returns None."""
        from uuid import uuid4
        
        update_dto = DeadLetterQueueUpdate(
            id=uuid4(),
            failure_reason="NewFailure",
        )
        result = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert result is None
    
    async def test_update_partial_only_updates_provided_fields(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that partial updates only modify provided fields."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            retry_count=2,
            is_active=True,
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        # Only update is_active, not other fields
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            is_active=False,
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert updated is not None
        assert updated.is_active is False
        assert updated.retry_count == 2  # Unchanged
        assert updated.failure_reason == "TestFailure"  # Unchanged


# =============================================================================
# DeadLetterQueue DAO Delete Tests
# =============================================================================

class TestDeadLetterQueueDAODelete:
    """Test delete operations for DeadLetterQueueDAO."""
    
    async def test_delete_existing_entry(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test deleting an existing DLQ entry."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        deleted = await DeadLetterQueueDAO.delete(created.id, session=db_session)
        
        assert deleted is True
        
        # Verify it's gone
        retrieved = await DeadLetterQueueDAO.get_by_id(created.id, session=db_session)
        assert retrieved is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession
    ):
        """Test that deleting nonexistent entry returns False."""
        from uuid import uuid4
        
        result = await DeadLetterQueueDAO.delete(uuid4(), session=db_session)
        
        assert result is False


# =============================================================================
# DeadLetterQueue DAO Exists Tests
# =============================================================================

class TestDeadLetterQueueDAOExists:
    """Test exists operations for DeadLetterQueueDAO."""
    
    async def test_exists_returns_true_for_existing(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that exists returns True for existing entry."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        exists = await DeadLetterQueueDAO.exists(created.id, session=db_session)
        
        assert exists is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession
    ):
        """Test that exists returns False for nonexistent entry."""
        from uuid import uuid4
        
        exists = await DeadLetterQueueDAO.exists(uuid4(), session=db_session)
        
        assert exists is False


# =============================================================================
# DeadLetterQueue DAO Count Tests
# =============================================================================

class TestDeadLetterQueueDAOCount:
    """Test count operations for DeadLetterQueueDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that count returns correct number of entries."""
        # Create 3 DLQ entries
        for i in range(3):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"count_task_{i}",
                status=TaskStatus.failed,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            dlq_create = DeadLetterQueueCreate(
                original_task_id=task.id,
                original_payload_json={"task": f"task_{i}"},
                failure_reason=f"Failure{i}",
                failure_details_json={"error": "test"},
            )
            await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        count = await DeadLetterQueueDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_returns_zero(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that count returns 0 for empty table."""
        count = await DeadLetterQueueDAO.count(session=db_session)
        
        assert count == 0


# =============================================================================
# DeadLetterQueue DAO Resolution Workflow Tests
# =============================================================================

class TestDeadLetterQueueDAOResolutionWorkflow:
    """Test DLQ resolution workflow."""
    
    async def test_get_active_unresolved_entries(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving active/unresolved DLQ entries."""
        # Create active and resolved entries
        for i in range(4):
            task = TaskEntity(
                user_id=test_user.id,
                task_type=f"resolve_task_{i}",
                status=TaskStatus.failed,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            dlq_create = DeadLetterQueueCreate(
                original_task_id=task.id,
                original_payload_json={"task": f"task_{i}"},
                failure_reason=f"Failure{i}",
                failure_details_json={"error": "test"},
                is_active=(i < 3),  # First 3 active, last 1 resolved
            )
            await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        active = await DeadLetterQueueDAO.get_all(is_active=True, session=db_session)
        
        assert len(active) == 3
    
    async def test_resolve_workflow_complete(
        self, db_session: AsyncSession, test_task: TaskEntity, test_user: UserEntity
    ):
        """Test complete resolution workflow with audit trail."""
        # Create DLQ entry
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="ConnectionTimeout",
            failure_details_json={"error": "Connection timed out"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        # Verify initial state
        assert created.is_active is True
        assert created.resolved_at is None
        assert created.resolved_by is None
        
        # Admin resolves the issue
        resolution_time = datetime.now(timezone.utc)
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            is_active=False,
            resolved_at=resolution_time,
            resolved_by=test_user.id,
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        # Verify audit trail
        assert updated.is_active is False
        assert updated.resolved_at is not None
        assert updated.resolved_by == test_user.id
        assert updated.resolved_at >= created.dead_lettered_at
    
    async def test_original_payload_preserved(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that original payload is properly preserved in JSONB."""
        complex_payload = {
            "task_id": str(test_task.id),
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
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json=complex_payload,
            failure_reason="ValidationError",
            failure_details_json={
                "validation_errors": [
                    {"field": "query", "error": "Too long"},
                ],
            },
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        # Verify payload is preserved exactly
        assert created.original_payload_json == complex_payload
        assert created.original_payload_json["payload"]["parameters"]["depth"] == 5
        assert len(created.original_payload_json["payload"]["parameters"]["sources"]) == 2


# =============================================================================
# DeadLetterQueue DAO JSONB Field Tests
# =============================================================================

class TestDeadLetterQueueDAOJSONBFields:
    """Test JSONB field handling."""
    
    async def test_original_payload_json_nested_structure(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that nested JSONB structures are preserved."""
        nested_payload = {
            "level1": {
                "level2": {
                    "level3": {
                        "data": [1, 2, 3],
                        "meta": {"key": "value"},
                    }
                }
            }
        }
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json=nested_payload,
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert created.original_payload_json["level1"]["level2"]["level3"]["data"] == [1, 2, 3]
    
    async def test_failure_details_json_complex_structure(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that complex failure_details_json is preserved."""
        failure_details = {
            "error": "Max retries exceeded",
            "stack_trace": "File 'app.py', line 42, in execute\n  raise TimeoutError",
            "retry_attempts": [
                {"attempt": 1, "error": "Timeout", "timestamp": "2026-03-22T10:00:00Z"},
                {"attempt": 2, "error": "Timeout", "timestamp": "2026-03-22T10:05:00Z"},
                {"attempt": 3, "error": "Timeout", "timestamp": "2026-03-22T10:10:00Z"},
            ],
            "metadata": {
                "agent_id": "agent-123",
                "session_id": "session-456",
            },
        }
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="MaxRetriesExceeded",
            failure_details_json=failure_details,
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert len(created.failure_details_json["retry_attempts"]) == 3
        assert created.failure_details_json["metadata"]["agent_id"] == "agent-123"


# =============================================================================
# DeadLetterQueue DAO Timestamp Tests
# =============================================================================

class TestDeadLetterQueueDAOTimestamps:
    """Test timestamp handling."""
    
    async def test_dead_lettered_at_auto_set(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that dead_lettered_at is auto-set on creation."""
        before = datetime.now(timezone.utc)
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        after = datetime.now(timezone.utc)
        
        assert created.dead_lettered_at is not None
        assert before <= created.dead_lettered_at <= after
    
    async def test_last_attempt_at_can_be_set(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that last_attempt_at can be explicitly set."""
        last_attempt = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
        
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            last_attempt_at=last_attempt,
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        
        assert created.last_attempt_at == last_attempt
    
    async def test_updated_at_changes_on_update(
        self, db_session: AsyncSession, test_task: TaskEntity
    ):
        """Test that updated_at changes when entry is updated."""
        dlq_create = DeadLetterQueueCreate(
            original_task_id=test_task.id,
            original_payload_json={"task": "test"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
        )
        created = await DeadLetterQueueDAO.create(dlq_create, session=db_session)
        original_updated_at = created.updated_at
        
        # Small delay to ensure timestamp difference
        import asyncio
        await asyncio.sleep(0.01)
        
        update_dto = DeadLetterQueueUpdate(
            id=created.id,
            failure_reason="UpdatedFailure",
        )
        updated = await DeadLetterQueueDAO.update(update_dto, session=db_session)
        
        assert updated.updated_at > original_updated_at