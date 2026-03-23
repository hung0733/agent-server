# pyright: reportMissingImports=false
"""
Tests for TaskDAO database operations including DAG operations.

This module tests CRUD operations for TaskDAO following the DAO pattern,
plus DAG (Directed Acyclic Graph) operations for task dependencies.

Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.task_dto import TaskCreate, Task, TaskUpdate, TaskDependencyCreate, TaskDependency, TaskDependencyUpdate
from db.dao.task_dao import TaskDAO, TaskDependencyDAO
from db.entity.task_entity import Task as TaskEntity, TaskDependency as TaskDependencyEntity
from db.entity.user_entity import User as UserEntity
from db.entity.llm_endpoint_entity import LLMEndpoint, LLMEndpointGroup  # Required for UserEntity relationships
from db.types import TaskStatus, Priority, DependencyType


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
    """Clean all task-related tables before and after tests."""
    # Clean before test
    await db_session.execute(delete(TaskDependencyEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    # Clean after test
    await db_session.rollback()
    await db_session.execute(delete(TaskDependencyEntity))
    await db_session.execute(delete(TaskEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, clean_data: None) -> UserEntity:
    """Create a test user for task ownership.
    
    Creates user directly via entity to avoid UserDAO which has
    relationships to LLMEndpointGroup/LLMEndpoint that aren't in the
    new entity registry.
    """
    user = UserEntity(
        username="tasktestuser",
        email="tasktest@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# =============================================================================
# Task DAO CRUD Tests
# =============================================================================

class TestTaskDAOCreate:
    """Test create operations for TaskDAO."""
    
    async def test_create_task_with_minimal_fields(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a task with only required fields."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="research",
        )
        
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        assert created_task is not None
        assert created_task.id is not None
        assert isinstance(created_task.id, UUID)
        assert created_task.user_id == test_user.id
        assert created_task.task_type == "research"
        assert created_task.status == TaskStatus.pending  # Default value
        assert created_task.priority == Priority.normal  # Default value
        assert created_task.retry_count == 0
        assert created_task.max_retries == 3
        assert created_task.created_at is not None
        assert created_task.updated_at is not None
        assert isinstance(created_task.created_at, datetime)
        assert isinstance(created_task.updated_at, datetime)
    
    async def test_create_task_with_all_fields(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a task with all fields specified."""
        scheduled_time = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="analysis",
            status=TaskStatus.running,
            priority=Priority.high,
            payload={"query": "test query", "limit": 10},
            max_retries=5,
            scheduled_at=scheduled_time,
            session_id="thread-test-123",
        )
        
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        assert created_task is not None
        assert created_task.task_type == "analysis"
        assert created_task.status == TaskStatus.running
        assert created_task.priority == Priority.high
        assert created_task.payload == {"query": "test query", "limit": 10}
        assert created_task.max_retries == 5
        assert created_task.scheduled_at == scheduled_time
        assert created_task.session_id == "thread-test-123"
    
    async def test_create_task_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that create returns a Task DTO, not an entity."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="code_generation",
        )
        
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        assert isinstance(created_task, Task)
    
    async def test_create_task_with_parent_task(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a child task with parent_task_id."""
        # Create parent task
        parent_create = TaskCreate(
            user_id=test_user.id,
            task_type="parent_task",
        )
        parent_task = await TaskDAO.create(parent_create, session=db_session)
        
        # Create child task
        child_create = TaskCreate(
            user_id=test_user.id,
            task_type="child_task",
            parent_task_id=parent_task.id,
        )
        child_task = await TaskDAO.create(child_create, session=db_session)
        
        assert child_task.parent_task_id == parent_task.id


class TestTaskDAOGetById:
    """Test get_by_id operations for TaskDAO."""
    
    async def test_get_by_id_returns_task(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving a task by ID."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="get_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        fetched_task = await TaskDAO.get_by_id(created_task.id, session=db_session)
        
        assert fetched_task is not None
        assert fetched_task.id == created_task.id
        assert fetched_task.task_type == "get_test"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        nonexistent_id = uuid4()
        
        result = await TaskDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_by_id returns a Task DTO."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="dto_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        fetched_task = await TaskDAO.get_by_id(created_task.id, session=db_session)
        
        assert isinstance(fetched_task, Task)


class TestTaskDAOGetByUserId:
    """Test get_by_user_id operations for TaskDAO."""
    
    async def test_get_by_user_id_returns_tasks(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving tasks by user ID."""
        for i in range(3):
            task_create = TaskCreate(
                user_id=test_user.id,
                task_type=f"user_task_{i}",
            )
            await TaskDAO.create(task_create, session=db_session)
        
        tasks = await TaskDAO.get_by_user_id(test_user.id, session=db_session)
        
        assert len(tasks) == 3
    
    async def test_get_by_user_id_empty_returns_empty_list(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_by_user_id returns empty list when no tasks."""
        tasks = await TaskDAO.get_by_user_id(test_user.id, session=db_session)
        
        assert tasks == []


class TestTaskDAOGetAll:
    """Test get_all operations for TaskDAO."""
    
    async def test_get_all_returns_all_tasks(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving all tasks."""
        for i in range(3):
            task_create = TaskCreate(
                user_id=test_user.id,
                task_type=f"all_task_{i}",
            )
            await TaskDAO.create(task_create, session=db_session)
        
        tasks = await TaskDAO.get_all(session=db_session)
        
        assert len(tasks) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_all returns empty list when no tasks exist."""
        tasks = await TaskDAO.get_all(session=db_session)
        
        assert tasks == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            task_create = TaskCreate(
                user_id=test_user.id,
                task_type=f"page_task_{i}",
            )
            await TaskDAO.create(task_create, session=db_session)
        
        # Test limit
        tasks_limited = await TaskDAO.get_all(limit=2, session=db_session)
        assert len(tasks_limited) == 2
        
        # Test offset
        tasks_offset = await TaskDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(tasks_offset) == 2
    
    async def test_get_all_with_status_filter(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all with status filter."""
        # Create tasks with different statuses
        task1 = TaskCreate(user_id=test_user.id, task_type="pending_task", status=TaskStatus.pending)
        task2 = TaskCreate(user_id=test_user.id, task_type="running_task", status=TaskStatus.running)
        task3 = TaskCreate(user_id=test_user.id, task_type="completed_task", status=TaskStatus.completed)
        
        await TaskDAO.create(task1, session=db_session)
        await TaskDAO.create(task2, session=db_session)
        await TaskDAO.create(task3, session=db_session)
        
        # Filter by pending status
        pending_tasks = await TaskDAO.get_all(status=TaskStatus.pending, session=db_session)
        assert len(pending_tasks) == 1
        assert pending_tasks[0].status == TaskStatus.pending


class TestTaskDAOUpdate:
    """Test update operations for TaskDAO."""
    
    async def test_update_task_status(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test updating a task's status."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="update_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        await asyncio.sleep(0.01)  # Ensure timestamp changes
        
        task_update = TaskUpdate(
            id=created_task.id,
            status=TaskStatus.running,
        )
        updated_task = await TaskDAO.update(task_update, session=db_session)
        
        assert updated_task is not None
        assert updated_task.status == TaskStatus.running
        assert updated_task.updated_at > created_task.updated_at
    
    async def test_update_task_result(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test updating a task's result."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="result_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        task_update = TaskUpdate(
            id=created_task.id,
            status=TaskStatus.completed,
            result={"output": "success", "data": [1, 2, 3]},
            completed_at=datetime.now(timezone.utc),
        )
        updated_task = await TaskDAO.update(task_update, session=db_session)
        
        assert updated_task is not None
        assert updated_task.result == {"output": "success", "data": [1, 2, 3]}
        assert updated_task.status == TaskStatus.completed
        assert updated_task.completed_at is not None
    
    async def test_update_task_error(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test updating a task with error information."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="error_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        task_update = TaskUpdate(
            id=created_task.id,
            status=TaskStatus.failed,
            error_message="Connection timeout after 30 seconds",
            retry_count=3,
        )
        updated_task = await TaskDAO.update(task_update, session=db_session)
        
        assert updated_task is not None
        assert updated_task.status == TaskStatus.failed
        assert updated_task.error_message == "Connection timeout after 30 seconds"
        assert updated_task.retry_count == 3
    
    async def test_update_nonexistent_task_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that updating a nonexistent task returns None."""
        from uuid import uuid4
        
        task_update = TaskUpdate(
            id=uuid4(),
            status=TaskStatus.running,
        )
        
        result = await TaskDAO.update(task_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that update returns a Task DTO."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="dto_update_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        task_update = TaskUpdate(
            id=created_task.id,
            priority=Priority.high,
        )
        updated_task = await TaskDAO.update(task_update, session=db_session)
        
        assert isinstance(updated_task, Task)


class TestTaskDAODelete:
    """Test delete operations for TaskDAO."""
    
    async def test_delete_existing_task(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test deleting an existing task."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="delete_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        result = await TaskDAO.delete(created_task.id, session=db_session)
        
        assert result is True
        
        # Verify task is deleted
        fetched = await TaskDAO.get_by_id(created_task.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_task_returns_false(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that deleting a nonexistent task returns False."""
        from uuid import uuid4
        
        result = await TaskDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestTaskDAOExists:
    """Test exists operations for TaskDAO."""
    
    async def test_exists_returns_true_for_existing_task(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that exists returns True for existing task."""
        task_create = TaskCreate(
            user_id=test_user.id,
            task_type="exists_test",
        )
        created_task = await TaskDAO.create(task_create, session=db_session)
        
        result = await TaskDAO.exists(created_task.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_task(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that exists returns False for nonexistent task."""
        from uuid import uuid4
        
        result = await TaskDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestTaskDAOCount:
    """Test count operations for TaskDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that count returns the correct number of tasks."""
        for i in range(3):
            task_create = TaskCreate(
                user_id=test_user.id,
                task_type=f"count_task_{i}",
            )
            await TaskDAO.create(task_create, session=db_session)
        
        count = await TaskDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that count returns 0 for empty table."""
        count = await TaskDAO.count(session=db_session)
        
        assert count == 0


# =============================================================================
# Task Dependency DAO CRUD Tests
# =============================================================================

class TestTaskDependencyDAOCreate:
    """Test create operations for TaskDependencyDAO."""
    
    async def test_create_dependency(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a task dependency."""
        # Create two tasks
        parent_create = TaskCreate(user_id=test_user.id, task_type="parent")
        parent_task = await TaskDAO.create(parent_create, session=db_session)
        
        child_create = TaskCreate(user_id=test_user.id, task_type="child")
        child_task = await TaskDAO.create(child_create, session=db_session)
        
        # Create dependency
        dep_create = TaskDependencyCreate(
            parent_task_id=parent_task.id,
            child_task_id=child_task.id,
            dependency_type=DependencyType.sequential,
        )
        
        created_dep = await TaskDependencyDAO.create(dep_create, session=db_session)
        
        assert created_dep is not None
        assert created_dep.id is not None
        assert created_dep.parent_task_id == parent_task.id
        assert created_dep.child_task_id == child_task.id
        assert created_dep.dependency_type == DependencyType.sequential
    
    async def test_create_dependency_with_condition(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test creating a conditional dependency with condition_json."""
        parent_create = TaskCreate(user_id=test_user.id, task_type="parent_cond")
        parent_task = await TaskDAO.create(parent_create, session=db_session)
        
        child_create = TaskCreate(user_id=test_user.id, task_type="child_cond")
        child_task = await TaskDAO.create(child_create, session=db_session)
        
        dep_create = TaskDependencyCreate(
            parent_task_id=parent_task.id,
            child_task_id=child_task.id,
            dependency_type=DependencyType.conditional,
            condition_json={"condition": "success", "expression": "parent.result.status == 'completed'"},
        )
        
        created_dep = await TaskDependencyDAO.create(dep_create, session=db_session)
        
        assert created_dep.dependency_type == DependencyType.conditional
        assert created_dep.condition_json is not None


class TestTaskDependencyDAOGetById:
    """Test get_by_id operations for TaskDependencyDAO."""
    
    async def test_get_by_id_returns_dependency(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving a dependency by ID."""
        parent_create = TaskCreate(user_id=test_user.id, task_type="p1")
        parent_task = await TaskDAO.create(parent_create, session=db_session)
        
        child_create = TaskCreate(user_id=test_user.id, task_type="c1")
        child_task = await TaskDAO.create(child_create, session=db_session)
        
        dep_create = TaskDependencyCreate(
            parent_task_id=parent_task.id,
            child_task_id=child_task.id,
        )
        created_dep = await TaskDependencyDAO.create(dep_create, session=db_session)
        
        fetched_dep = await TaskDependencyDAO.get_by_id(created_dep.id, session=db_session)
        
        assert fetched_dep is not None
        assert fetched_dep.id == created_dep.id
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        result = await TaskDependencyDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None


class TestTaskDependencyDAOGetByParentTaskId:
    """Test get_by_parent_task_id operations for TaskDependencyDAO."""
    
    async def test_get_by_parent_task_id_returns_dependencies(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving dependencies by parent task ID."""
        parent_create = TaskCreate(user_id=test_user.id, task_type="parent_multi")
        parent_task = await TaskDAO.create(parent_create, session=db_session)
        
        # Create multiple children
        children = []
        for i in range(3):
            child_create = TaskCreate(user_id=test_user.id, task_type=f"child_{i}")
            child = await TaskDAO.create(child_create, session=db_session)
            children.append(child)
            
            dep_create = TaskDependencyCreate(
                parent_task_id=parent_task.id,
                child_task_id=child.id,
            )
            await TaskDependencyDAO.create(dep_create, session=db_session)
        
        deps = await TaskDependencyDAO.get_by_parent_task_id(parent_task.id, session=db_session)
        
        assert len(deps) == 3
        child_ids = {d.child_task_id for d in deps}
        assert all(c.id in child_ids for c in children)
    
    async def test_get_by_parent_task_id_empty_returns_empty_list(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_by_parent_task_id returns empty list when no dependencies."""
        task = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="orphan"),
            session=db_session
        )
        
        deps = await TaskDependencyDAO.get_by_parent_task_id(task.id, session=db_session)
        
        assert deps == []


class TestTaskDependencyDAOGetByChildTaskId:
    """Test get_by_child_task_id operations for TaskDependencyDAO."""
    
    async def test_get_by_child_task_id_returns_dependencies(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving dependencies by child task ID."""
        # Create multiple parents pointing to same child
        child_create = TaskCreate(user_id=test_user.id, task_type="child_multi")
        child_task = await TaskDAO.create(child_create, session=db_session)
        
        parents = []
        for i in range(3):
            parent_create = TaskCreate(user_id=test_user.id, task_type=f"parent_{i}")
            parent = await TaskDAO.create(parent_create, session=db_session)
            parents.append(parent)
            
            dep_create = TaskDependencyCreate(
                parent_task_id=parent.id,
                child_task_id=child_task.id,
            )
            await TaskDependencyDAO.create(dep_create, session=db_session)
        
        deps = await TaskDependencyDAO.get_by_child_task_id(child_task.id, session=db_session)
        
        assert len(deps) == 3
        parent_ids = {d.parent_task_id for d in deps}
        assert all(p.id in parent_ids for p in parents)
    
    async def test_get_by_child_task_id_empty_returns_empty_list(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_by_child_task_id returns empty list when no dependencies."""
        task = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="independent"),
            session=db_session
        )
        
        deps = await TaskDependencyDAO.get_by_child_task_id(task.id, session=db_session)
        
        assert deps == []


class TestTaskDependencyDAOGetAll:
    """Test get_all operations for TaskDependencyDAO."""
    
    async def test_get_all_returns_all_dependencies(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test retrieving all dependencies."""
        for i in range(3):
            parent = await TaskDAO.create(
                TaskCreate(user_id=test_user.id, task_type=f"p_all_{i}"),
                session=db_session
            )
            child = await TaskDAO.create(
                TaskCreate(user_id=test_user.id, task_type=f"c_all_{i}"),
                session=db_session
            )
            await TaskDependencyDAO.create(
                TaskDependencyCreate(parent_task_id=parent.id, child_task_id=child.id),
                session=db_session
            )
        
        deps = await TaskDependencyDAO.get_all(session=db_session)
        
        assert len(deps) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that get_all returns empty list when no dependencies exist."""
        deps = await TaskDependencyDAO.get_all(session=db_session)
        
        assert deps == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            parent = await TaskDAO.create(
                TaskCreate(user_id=test_user.id, task_type=f"p_page_{i}"),
                session=db_session
            )
            child = await TaskDAO.create(
                TaskCreate(user_id=test_user.id, task_type=f"c_page_{i}"),
                session=db_session
            )
            await TaskDependencyDAO.create(
                TaskDependencyCreate(parent_task_id=parent.id, child_task_id=child.id),
                session=db_session
            )
        
        # Test limit
        deps_limited = await TaskDependencyDAO.get_all(limit=2, session=db_session)
        assert len(deps_limited) == 2
        
        # Test offset
        deps_offset = await TaskDependencyDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(deps_offset) == 2


class TestTaskDependencyDAOUpdate:
    """Test update operations for TaskDependencyDAO."""
    
    async def test_update_dependency_type(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test updating a dependency's type."""
        parent = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="p_update"),
            session=db_session
        )
        child = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="c_update"),
            session=db_session
        )
        
        created_dep = await TaskDependencyDAO.create(
            TaskDependencyCreate(
                parent_task_id=parent.id,
                child_task_id=child.id,
                dependency_type=DependencyType.sequential,
            ),
            session=db_session
        )
        
        update_dto = TaskDependencyUpdate(
            id=created_dep.id,
            dependency_type=DependencyType.parallel,
        )
        updated_dep = await TaskDependencyDAO.update(update_dto, session=db_session)
        
        assert updated_dep is not None
        assert updated_dep.dependency_type == DependencyType.parallel
    
    async def test_update_dependency_condition_json(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test updating a dependency's condition_json."""
        parent = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="p_cond"),
            session=db_session
        )
        child = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="c_cond"),
            session=db_session
        )
        
        created_dep = await TaskDependencyDAO.create(
            TaskDependencyCreate(
                parent_task_id=parent.id,
                child_task_id=child.id,
            ),
            session=db_session
        )
        
        new_condition = {"condition": "failure", "expression": "parent.result.error_code == 500"}
        update_dto = TaskDependencyUpdate(
            id=created_dep.id,
            dependency_type=DependencyType.conditional,
            condition_json=new_condition,
        )
        updated_dep = await TaskDependencyDAO.update(update_dto, session=db_session)
        
        assert updated_dep is not None
        assert updated_dep.dependency_type == DependencyType.conditional
        assert updated_dep.condition_json == new_condition
    
    async def test_update_nonexistent_dependency_returns_none(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that updating a nonexistent dependency returns None."""
        from uuid import uuid4
        
        update_dto = TaskDependencyUpdate(
            id=uuid4(),
            dependency_type=DependencyType.parallel,
        )
        
        result = await TaskDependencyDAO.update(update_dto, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that update returns a TaskDependency DTO."""
        parent = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="p_dto"),
            session=db_session
        )
        child = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="c_dto"),
            session=db_session
        )
        
        created_dep = await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=parent.id, child_task_id=child.id),
            session=db_session
        )
        
        update_dto = TaskDependencyUpdate(
            id=created_dep.id,
            dependency_type=DependencyType.conditional,
        )
        updated_dep = await TaskDependencyDAO.update(update_dto, session=db_session)
        
        assert isinstance(updated_dep, TaskDependency)


class TestTaskDependencyDAODelete:
    """Test delete operations for TaskDependencyDAO."""
    
    async def test_delete_dependency(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test deleting a task dependency."""
        parent_create = TaskCreate(user_id=test_user.id, task_type="p_del")
        parent_task = await TaskDAO.create(parent_create, session=db_session)
        
        child_create = TaskCreate(user_id=test_user.id, task_type="c_del")
        child_task = await TaskDAO.create(child_create, session=db_session)
        
        dep_create = TaskDependencyCreate(
            parent_task_id=parent_task.id,
            child_task_id=child_task.id,
        )
        created_dep = await TaskDependencyDAO.create(dep_create, session=db_session)
        
        result = await TaskDependencyDAO.delete(created_dep.id, session=db_session)
        
        assert result is True
        
        # Verify dependency is deleted
        fetched = await TaskDependencyDAO.get_by_id(created_dep.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_dependency_returns_false(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that deleting a nonexistent dependency returns False."""
        from uuid import uuid4
        
        result = await TaskDependencyDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestTaskDependencyDAOExists:
    """Test exists operations for TaskDependencyDAO."""
    
    async def test_exists_returns_true_for_existing_dependency(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that exists returns True for existing dependency."""
        parent = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="p_exists"),
            session=db_session
        )
        child = await TaskDAO.create(
            TaskCreate(user_id=test_user.id, task_type="c_exists"),
            session=db_session
        )
        
        created_dep = await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=parent.id, child_task_id=child.id),
            session=db_session
        )
        
        result = await TaskDependencyDAO.exists(created_dep.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_dependency(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that exists returns False for nonexistent dependency."""
        from uuid import uuid4
        
        result = await TaskDependencyDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestTaskDependencyDAOCount:
    """Test count operations for TaskDependencyDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that count returns the correct number of dependencies."""
        for i in range(3):
            parent = await TaskDAO.create(
                TaskCreate(user_id=test_user.id, task_type=f"p_count_{i}"),
                session=db_session
            )
            child = await TaskDAO.create(
                TaskCreate(user_id=test_user.id, task_type=f"c_count_{i}"),
                session=db_session
            )
            await TaskDependencyDAO.create(
                TaskDependencyCreate(parent_task_id=parent.id, child_task_id=child.id),
                session=db_session
            )
        
        count = await TaskDependencyDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_data: None
    ):
        """Test that count returns 0 for empty table."""
        count = await TaskDependencyDAO.count(session=db_session)
        
        assert count == 0


# =============================================================================
# DAG Operations Tests
# =============================================================================

class TestTaskDAODetectCycle:
    """Test detect_cycle operations for TaskDAO."""
    
    async def test_detect_cycle_no_cycle(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that detect_cycle returns None when no cycle would be created."""
        # Create three tasks: A -> B -> C (linear chain)
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        
        # Create dependencies: A -> B -> C
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_c.id),
            session=db_session
        )
        
        # Check if adding D -> A would create cycle (it shouldn't)
        task_d = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="D"), session=db_session)
        
        cycle = await TaskDAO.detect_cycle(task_d.id, task_a.id, session=db_session)
        
        assert cycle is None
    
    async def test_detect_cycle_simple_cycle(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that detect_cycle detects a simple cycle."""
        # Create tasks: A -> B
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        
        # Create dependency: A -> B
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        
        # Check if adding B -> A would create cycle (it would)
        cycle = await TaskDAO.detect_cycle(task_b.id, task_a.id, session=db_session)
        
        assert cycle is not None
        assert task_a.id in cycle
        assert task_b.id in cycle
    
    async def test_detect_cycle_complex_cycle(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that detect_cycle detects a cycle in a longer chain."""
        # Create tasks: A -> B -> C -> D
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        task_d = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="D"), session=db_session)
        
        # Create dependencies: A -> B -> C -> D
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_c.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_c.id, child_task_id=task_d.id),
            session=db_session
        )
        
        # Check if adding D -> A would create cycle (it would)
        cycle = await TaskDAO.detect_cycle(task_d.id, task_a.id, session=db_session)
        
        assert cycle is not None
        # The cycle should contain all involved tasks
        assert task_a.id in cycle


class TestTaskDAOGetAncestors:
    """Test get_ancestors operations for TaskDAO."""
    
    async def test_get_ancestors_linear_chain(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting ancestors in a linear chain."""
        # Create tasks: A -> B -> C
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        
        # Create dependencies: A -> B -> C
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_c.id),
            session=db_session
        )
        
        # Get ancestors of C (should be A and B)
        ancestors = await TaskDAO.get_ancestors(task_c.id, session=db_session)
        
        assert len(ancestors) == 2
        assert task_a.id in ancestors
        assert task_b.id in ancestors
    
    async def test_get_ancestors_diamond_shape(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting ancestors in a diamond shape (A -> B, A -> C, B -> D, C -> D)."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        task_d = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="D"), session=db_session)
        
        # Create diamond: A -> B, A -> C, B -> D, C -> D
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_c.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_d.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_c.id, child_task_id=task_d.id),
            session=db_session
        )
        
        # Get ancestors of D (should be A, B, C)
        ancestors = await TaskDAO.get_ancestors(task_d.id, session=db_session)
        
        assert len(ancestors) == 3
        assert task_a.id in ancestors
        assert task_b.id in ancestors
        assert task_c.id in ancestors
    
    async def test_get_ancestors_no_ancestors(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting ancestors for a task with no ancestors."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="root"), session=db_session)
        
        ancestors = await TaskDAO.get_ancestors(task_a.id, session=db_session)
        
        assert len(ancestors) == 0


class TestTaskDAOGetDescendants:
    """Test get_descendants operations for TaskDAO."""
    
    async def test_get_descendants_linear_chain(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting descendants in a linear chain."""
        # Create tasks: A -> B -> C
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        
        # Create dependencies: A -> B -> C
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_c.id),
            session=db_session
        )
        
        # Get descendants of A (should be B and C)
        descendants = await TaskDAO.get_descendants(task_a.id, session=db_session)
        
        assert len(descendants) == 2
        assert task_b.id in descendants
        assert task_c.id in descendants
    
    async def test_get_descendants_diamond_shape(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting descendants in a diamond shape."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        task_d = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="D"), session=db_session)
        
        # Create diamond: A -> B, A -> C, B -> D, C -> D
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_c.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_d.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_c.id, child_task_id=task_d.id),
            session=db_session
        )
        
        # Get descendants of A (should be B, C, D)
        descendants = await TaskDAO.get_descendants(task_a.id, session=db_session)
        
        assert len(descendants) == 3
        assert task_b.id in descendants
        assert task_c.id in descendants
        assert task_d.id in descendants
    
    async def test_get_descendants_no_descendants(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting descendants for a task with no descendants."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="leaf"), session=db_session)
        
        descendants = await TaskDAO.get_descendants(task_a.id, session=db_session)
        
        assert len(descendants) == 0


class TestTaskDAOGetDependencyOrder:
    """Test get_dependency_order operations for TaskDAO."""
    
    async def test_get_dependency_order_linear(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting dependency order for a linear chain."""
        # Create tasks: A -> B -> C
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        
        # Create dependencies: A -> B -> C
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_c.id),
            session=db_session
        )
        
        # Get dependency order
        order = await TaskDAO.get_dependency_order([task_a.id, task_b.id, task_c.id], session=db_session)
        
        assert len(order) == 3
        # A should come before B, B should come before C
        assert order.index(task_a.id) < order.index(task_b.id)
        assert order.index(task_b.id) < order.index(task_c.id)
    
    async def test_get_dependency_order_diamond(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test getting dependency order for a diamond shape."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        task_c = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="C"), session=db_session)
        task_d = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="D"), session=db_session)
        
        # Create diamond: A -> B, A -> C, B -> D, C -> D
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_c.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_b.id, child_task_id=task_d.id),
            session=db_session
        )
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_c.id, child_task_id=task_d.id),
            session=db_session
        )
        
        # Get dependency order
        order = await TaskDAO.get_dependency_order([task_a.id, task_b.id, task_c.id, task_d.id], session=db_session)
        
        assert len(order) == 4
        # A should come before B and C
        assert order.index(task_a.id) < order.index(task_b.id)
        assert order.index(task_a.id) < order.index(task_c.id)
        # B and C should come before D
        assert order.index(task_b.id) < order.index(task_d.id)
        assert order.index(task_c.id) < order.index(task_d.id)
    
    async def test_get_dependency_order_empty_list(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that get_dependency_order returns empty list for empty input."""
        order = await TaskDAO.get_dependency_order([], session=db_session)
        
        assert order == []


class TestTaskDAOValidateNewDependency:
    """Test validate_new_dependency operations for TaskDAO."""
    
    async def test_validate_new_dependency_valid(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test validating a valid new dependency."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        
        # Should not raise any exception
        await TaskDAO.validate_new_dependency(task_a.id, task_b.id, session=db_session)
    
    async def test_validate_new_dependency_self_reference(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that self-reference dependency raises ValueError."""
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        
        with pytest.raises(ValueError) as exc_info:
            await TaskDAO.validate_new_dependency(task_a.id, task_a.id, session=db_session)
        
        assert "cannot depend on itself" in str(exc_info.value).lower()
    
    async def test_validate_new_dependency_cycle(
        self, db_session: AsyncSession, test_user: UserEntity
    ):
        """Test that cycle-creating dependency raises CycleDetectedError."""
        from db.dao.task_dao import CycleDetectedError
        
        # Create tasks: A -> B
        task_a = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="A"), session=db_session)
        task_b = await TaskDAO.create(TaskCreate(user_id=test_user.id, task_type="B"), session=db_session)
        
        # Create dependency: A -> B
        await TaskDependencyDAO.create(
            TaskDependencyCreate(parent_task_id=task_a.id, child_task_id=task_b.id),
            session=db_session
        )
        
        # Trying to add B -> A should raise CycleDetectedError
        with pytest.raises(CycleDetectedError):
            await TaskDAO.validate_new_dependency(task_b.id, task_a.id, session=db_session)


class TestCycleDetectedError:
    """Test CycleDetectedError exception."""
    
    def test_cycle_detected_error_with_path(self):
        """Test creating CycleDetectedError with a cycle path."""
        from db.dao.task_dao import CycleDetectedError
        from uuid import uuid4
        
        path = [uuid4(), uuid4(), uuid4()]
        error = CycleDetectedError("Cycle detected", cycle_path=path)
        
        assert str(error) == "Cycle detected"
        assert error.cycle_path == path
    
    def test_cycle_detected_error_without_path(self):
        """Test creating CycleDetectedError without a cycle path."""
        from db.dao.task_dao import CycleDetectedError
        
        error = CycleDetectedError("Cycle detected")
        
        assert error.cycle_path == []