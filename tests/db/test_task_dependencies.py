# pyright: reportMissingImports=false
"""
Tests for task dependency database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, unique constraints, self-reference check,
and cycle detection for task_dependencies table.
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
from db.schema.task_dependencies import TaskDependency
from db.schema.tasks import Task
from db.types import DependencyType, TaskStatus, gen_random_uuid
from db.queries.task_dag import (
    CycleDetectedError,
    detect_cycle,
    get_ancestors,
    get_descendants,
    get_dependency_order,
    validate_new_dependency,
)


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
        
        # Create tasks table with all constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID,
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
        
        # Create task_dependencies table with all constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_dependencies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parent_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                child_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                dependency_type TEXT NOT NULL DEFAULT 'sequential'
                    CHECK (dependency_type IN ('sequential', 'parallel', 'conditional')),
                condition_json JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_task_dependencies_no_self_reference CHECK (parent_task_id != child_task_id),
                CONSTRAINT uq_task_dependencies_parent_child UNIQUE (parent_task_id, child_task_id)
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_deps_parent ON task_dependencies(parent_task_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_deps_child ON task_dependencies(child_task_id)
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS task_dependencies"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


async def _create_test_user(db_session: AsyncSession) -> UUID:
    """Helper to create a test user and return its ID."""
    user_id = gen_random_uuid()
    await db_session.execute(text(f"""
        INSERT INTO users (id, username, email) 
        VALUES ('{user_id}', 'testuser_{user_id}', 'test_{user_id}@example.com')
    """))
    await db_session.commit()
    return user_id


async def _create_test_task(
    db_session: AsyncSession, 
    user_id: UUID, 
    task_type: str = "test_task"
) -> Task:
    """Helper to create a test task and return it."""
    task = Task(
        user_id=user_id,
        task_type=task_type,
        status=TaskStatus.pending,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestTaskDependencySchema:
    """Test task_dependencies schema creation and structure."""
    
    async def test_table_exists(self, db_session: AsyncSession):
        """Test that the task_dependencies table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'task_dependencies'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "task_dependencies"
    
    async def test_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in task_dependencies table."""
        expected_columns = {
            'id', 'parent_task_id', 'child_task_id', 
            'dependency_type', 'condition_json', 'created_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'task_dependencies'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'task_dependencies'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_deps_parent' in indexes
        assert 'idx_deps_child' in indexes
    
    async def test_unique_constraint_exists(self, db_session: AsyncSession):
        """Test that the unique constraint on (parent_task_id, child_task_id) exists."""
        result = await db_session.execute(
            text("""
                SELECT conname 
                FROM pg_constraint 
                WHERE conrelid = 'task_dependencies'::regclass 
                AND contype = 'u'
            """)
        )
        constraints = {row[0] for row in result.fetchall()}
        
        assert 'uq_task_dependencies_parent_child' in constraints
    
    async def test_check_constraint_exists(self, db_session: AsyncSession):
        """Test that the self-reference check constraint exists."""
        result = await db_session.execute(
            text("""
                SELECT conname 
                FROM pg_constraint 
                WHERE conrelid = 'task_dependencies'::regclass 
                AND contype = 'c'
            """)
        )
        constraints = {row[0] for row in result.fetchall()}
        
        assert 'ck_task_dependencies_no_self_reference' in constraints


class TestTaskDependencyCRUD:
    """Test CRUD operations for TaskDependency model."""
    
    async def test_create_dependency_minimal(self, db_session: AsyncSession):
        """Test creating a task dependency with minimal fields."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
        )
        db_session.add(dependency)
        await db_session.commit()
        await db_session.refresh(dependency)
        
        assert dependency.id is not None
        assert isinstance(dependency.id, UUID)
        assert dependency.parent_task_id == parent.id
        assert dependency.child_task_id == child.id
        assert dependency.dependency_type == DependencyType.sequential
        assert dependency.condition_json is None
        assert dependency.created_at is not None
    
    async def test_create_dependency_full(self, db_session: AsyncSession):
        """Test creating a task dependency with all fields."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        condition = {
            "condition": "success",
            "expression": "parent.result.status == 'completed'"
        }
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            dependency_type=DependencyType.conditional,
            condition_json=condition,
        )
        db_session.add(dependency)
        await db_session.commit()
        await db_session.refresh(dependency)
        
        assert dependency.dependency_type == DependencyType.conditional
        assert isinstance(dependency.condition_json, dict)
        assert dependency.condition_json["condition"] == "success"
    
    async def test_create_all_dependency_types(self, db_session: AsyncSession):
        """Test creating dependencies with all dependency types."""
        user_id = await _create_test_user(db_session)
        
        for dep_type in DependencyType:
            parent = await _create_test_task(db_session, user_id, f"parent_{dep_type.value}")
            child = await _create_test_task(db_session, user_id, f"child_{dep_type.value}")
            
            dependency = TaskDependency(
                parent_task_id=parent.id,
                child_task_id=child.id,
                dependency_type=dep_type,
            )
            db_session.add(dependency)
            await db_session.commit()
            await db_session.refresh(dependency)
            
            assert dependency.dependency_type == dep_type
    
    async def test_update_dependency(self, db_session: AsyncSession):
        """Test updating a task dependency."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            dependency_type=DependencyType.sequential,
        )
        db_session.add(dependency)
        await db_session.commit()
        
        # Update
        dependency.dependency_type = DependencyType.conditional
        dependency.condition_json = {"condition": "retry_on_failure"}
        await db_session.commit()
        await db_session.refresh(dependency)
        
        assert dependency.dependency_type == DependencyType.conditional
        assert dependency.condition_json["condition"] == "retry_on_failure"
    
    async def test_delete_dependency(self, db_session: AsyncSession):
        """Test deleting a task dependency."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
        )
        db_session.add(dependency)
        await db_session.commit()
        
        await db_session.delete(dependency)
        await db_session.commit()
        
        result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.id == dependency.id)
        )
        assert result.scalar_one_or_none() is None


class TestSelfReferenceConstraint:
    """Test the self-reference check constraint."""
    
    async def test_self_reference_prevented(self, db_session: AsyncSession):
        """Test that a task cannot depend on itself."""
        user_id = await _create_test_user(db_session)
        task = await _create_test_task(db_session, user_id, "self_ref_task")
        
        dependency = TaskDependency(
            parent_task_id=task.id,
            child_task_id=task.id,  # Same task!
        )
        db_session.add(dependency)
        
        with pytest.raises(IntegrityError) as exc_info:
            await db_session.commit()
        
        assert "ck_task_dependencies_no_self_reference" in str(exc_info.value)


class TestUniqueConstraint:
    """Test the unique constraint on (parent_task_id, child_task_id)."""
    
    async def test_duplicate_dependency_prevented(self, db_session: AsyncSession):
        """Test that duplicate dependencies between same tasks are prevented."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        # First dependency
        dep1 = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            dependency_type=DependencyType.sequential,
        )
        db_session.add(dep1)
        await db_session.commit()
        
        # Attempt duplicate
        dep2 = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            dependency_type=DependencyType.conditional,  # Different type
        )
        db_session.add(dep2)
        
        with pytest.raises(IntegrityError) as exc_info:
            await db_session.commit()
        
        assert "uq_task_dependencies_parent_child" in str(exc_info.value)
    
    async def test_same_child_different_parents_allowed(self, db_session: AsyncSession):
        """Test that a child can have multiple different parents."""
        user_id = await _create_test_user(db_session)
        
        parent1 = await _create_test_task(db_session, user_id, "parent1")
        parent2 = await _create_test_task(db_session, user_id, "parent2")
        child = await _create_test_task(db_session, user_id, "child")
        
        dep1 = TaskDependency(
            parent_task_id=parent1.id,
            child_task_id=child.id,
        )
        dep2 = TaskDependency(
            parent_task_id=parent2.id,
            child_task_id=child.id,
        )
        db_session.add_all([dep1, dep2])
        await db_session.commit()
        
        # Should succeed
        result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.child_task_id == child.id)
        )
        deps = result.scalars().all()
        assert len(deps) == 2
    
    async def test_same_parent_different_children_allowed(self, db_session: AsyncSession):
        """Test that a parent can have multiple different children."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent")
        child1 = await _create_test_task(db_session, user_id, "child1")
        child2 = await _create_test_task(db_session, user_id, "child2")
        
        dep1 = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child1.id,
        )
        dep2 = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child2.id,
        )
        db_session.add_all([dep1, dep2])
        await db_session.commit()
        
        # Should succeed
        result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.parent_task_id == parent.id)
        )
        deps = result.scalars().all()
        assert len(deps) == 2


class TestForeignKeyConstraints:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_parent_task_enforced(self, db_session: AsyncSession):
        """Test that parent_task_id FK constraint is enforced."""
        user_id = await _create_test_user(db_session)
        child = await _create_test_task(db_session, user_id, "child_task")
        
        fake_parent_id = uuid4()
        
        dependency = TaskDependency(
            parent_task_id=fake_parent_id,
            child_task_id=child.id,
        )
        db_session.add(dependency)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_fk_child_task_enforced(self, db_session: AsyncSession):
        """Test that child_task_id FK constraint is enforced."""
        user_id = await _create_test_user(db_session)
        parent = await _create_test_task(db_session, user_id, "parent_task")
        
        fake_child_id = uuid4()
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=fake_child_id,
        )
        db_session.add(dependency)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_parent_task(self, db_session: AsyncSession):
        """Test that deleting parent task cascades to dependencies."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
        )
        db_session.add(dependency)
        await db_session.commit()
        
        # Delete parent task
        await db_session.delete(parent)
        await db_session.commit()
        
        # Verify dependency is deleted
        result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.id == dependency.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_cascade_delete_child_task(self, db_session: AsyncSession):
        """Test that deleting child task cascades to dependencies."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent_task")
        child = await _create_test_task(db_session, user_id, "child_task")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
        )
        db_session.add(dependency)
        await db_session.commit()
        
        # Delete child task
        await db_session.delete(child)
        await db_session.commit()
        
        # Verify dependency is deleted
        result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.id == dependency.id)
        )
        assert result.scalar_one_or_none() is None


class TestCycleDetection:
    """Test cycle detection for task dependencies."""
    
    async def test_no_cycle_simple(self, db_session: AsyncSession):
        """Test no cycle detected for simple linear dependency."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # A -> B (no cycle)
        cycle = await detect_cycle(db_session, task_a.id, task_b.id)
        assert cycle is None
    
    async def test_direct_cycle_detection(self, db_session: AsyncSession):
        """Test detection of direct cycle A -> B, B -> A."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # Create A -> B
        dep = TaskDependency(
            parent_task_id=task_a.id,
            child_task_id=task_b.id,
        )
        db_session.add(dep)
        await db_session.commit()
        
        # Try to add B -> A (would create cycle)
        cycle = await detect_cycle(db_session, task_b.id, task_a.id)
        assert cycle is not None
        assert task_b.id in cycle
        assert task_a.id in cycle
    
    async def test_indirect_cycle_detection(self, db_session: AsyncSession):
        """Test detection of indirect cycle A -> B -> C -> A."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        task_c = await _create_test_task(db_session, user_id, "task_c")
        
        # Create A -> B -> C
        dep1 = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        dep2 = TaskDependency(parent_task_id=task_b.id, child_task_id=task_c.id)
        db_session.add_all([dep1, dep2])
        await db_session.commit()
        
        # Try to add C -> A (would create cycle A -> B -> C -> A)
        cycle = await detect_cycle(db_session, task_c.id, task_a.id)
        assert cycle is not None
    
    async def test_validate_new_dependency_success(self, db_session: AsyncSession):
        """Test validate_new_dependency succeeds for valid dependency."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # Should not raise
        await validate_new_dependency(db_session, task_a.id, task_b.id)
    
    async def test_validate_new_dependency_self_reference(self, db_session: AsyncSession):
        """Test validate_new_dependency rejects self-reference."""
        user_id = await _create_test_user(db_session)
        task = await _create_test_task(db_session, user_id, "task")
        
        with pytest.raises(ValueError) as exc_info:
            await validate_new_dependency(db_session, task.id, task.id)
        
        assert "cannot depend on itself" in str(exc_info.value)
    
    async def test_validate_new_dependency_cycle(self, db_session: AsyncSession):
        """Test validate_new_dependency rejects cycle-creating dependency."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # Create A -> B
        dep = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        db_session.add(dep)
        await db_session.commit()
        
        # Try to add B -> A
        with pytest.raises(CycleDetectedError):
            await validate_new_dependency(db_session, task_b.id, task_a.id)


class TestAncestorsAndDescendants:
    """Test ancestor and descendant traversal."""
    
    async def test_get_ancestors_direct(self, db_session: AsyncSession):
        """Test getting direct ancestors of a task."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # A -> B (A is ancestor of B)
        dep = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        db_session.add(dep)
        await db_session.commit()
        
        ancestors = await get_ancestors(db_session, task_b.id)
        assert task_a.id in ancestors
        assert len(ancestors) == 1
    
    async def test_get_ancestors_chain(self, db_session: AsyncSession):
        """Test getting ancestors in a chain A -> B -> C."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        task_c = await _create_test_task(db_session, user_id, "task_c")
        
        # A -> B -> C
        dep1 = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        dep2 = TaskDependency(parent_task_id=task_b.id, child_task_id=task_c.id)
        db_session.add_all([dep1, dep2])
        await db_session.commit()
        
        ancestors = await get_ancestors(db_session, task_c.id)
        assert task_a.id in ancestors
        assert task_b.id in ancestors
        assert len(ancestors) == 2
    
    async def test_get_descendants_direct(self, db_session: AsyncSession):
        """Test getting direct descendants of a task."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # A -> B (B is descendant of A)
        dep = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        db_session.add(dep)
        await db_session.commit()
        
        descendants = await get_descendants(db_session, task_a.id)
        assert task_b.id in descendants
        assert len(descendants) == 1
    
    async def test_get_descendants_chain(self, db_session: AsyncSession):
        """Test getting descendants in a chain A -> B -> C."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        task_c = await _create_test_task(db_session, user_id, "task_c")
        
        # A -> B -> C
        dep1 = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        dep2 = TaskDependency(parent_task_id=task_b.id, child_task_id=task_c.id)
        db_session.add_all([dep1, dep2])
        await db_session.commit()
        
        descendants = await get_descendants(db_session, task_a.id)
        assert task_b.id in descendants
        assert task_c.id in descendants
        assert len(descendants) == 2


class TestDependencyOrder:
    """Test topological sorting of dependencies."""
    
    async def test_get_dependency_order_linear(self, db_session: AsyncSession):
        """Test topological sort of linear chain A -> B -> C."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        task_c = await _create_test_task(db_session, user_id, "task_c")
        
        # A -> B -> C
        dep1 = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        dep2 = TaskDependency(parent_task_id=task_b.id, child_task_id=task_c.id)
        db_session.add_all([dep1, dep2])
        await db_session.commit()
        
        order = await get_dependency_order(db_session, [task_a.id, task_b.id, task_c.id])
        
        # A should come before B, B before C
        assert order.index(task_a.id) < order.index(task_b.id)
        assert order.index(task_b.id) < order.index(task_c.id)
    
    async def test_get_dependency_order_diamond(self, db_session: AsyncSession):
        """Test topological sort of diamond pattern A -> B, A -> C, B -> D, C -> D."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        task_c = await _create_test_task(db_session, user_id, "task_c")
        task_d = await _create_test_task(db_session, user_id, "task_d")
        
        # A -> B, A -> C, B -> D, C -> D
        dep1 = TaskDependency(parent_task_id=task_a.id, child_task_id=task_b.id)
        dep2 = TaskDependency(parent_task_id=task_a.id, child_task_id=task_c.id)
        dep3 = TaskDependency(parent_task_id=task_b.id, child_task_id=task_d.id)
        dep4 = TaskDependency(parent_task_id=task_c.id, child_task_id=task_d.id)
        db_session.add_all([dep1, dep2, dep3, dep4])
        await db_session.commit()
        
        order = await get_dependency_order(
            db_session, 
            [task_a.id, task_b.id, task_c.id, task_d.id]
        )
        
        # A should come before B and C, B and C should come before D
        assert order.index(task_a.id) < order.index(task_b.id)
        assert order.index(task_a.id) < order.index(task_c.id)
        assert order.index(task_b.id) < order.index(task_d.id)
        assert order.index(task_c.id) < order.index(task_d.id)
    
    async def test_get_dependency_order_cycle_raises(self, db_session: AsyncSession):
        """Test that cycle in dependencies raises CycleDetectedError."""
        user_id = await _create_test_user(db_session)
        
        task_a = await _create_test_task(db_session, user_id, "task_a")
        task_b = await _create_test_task(db_session, user_id, "task_b")
        
        # Create A -> B -> A (cycle via raw SQL to bypass validation)
        await db_session.execute(text(f"""
            INSERT INTO task_dependencies (parent_task_id, child_task_id, dependency_type)
            VALUES ('{task_a.id}', '{task_b.id}', 'sequential')
        """))
        await db_session.execute(text(f"""
            INSERT INTO task_dependencies (parent_task_id, child_task_id, dependency_type)
            VALUES ('{task_b.id}', '{task_a.id}', 'sequential')
        """))
        await db_session.commit()
        
        with pytest.raises(CycleDetectedError):
            await get_dependency_order(db_session, [task_a.id, task_b.id])


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_task_dependency_create_validation(self):
        """Test TaskDependencyCreate model validation."""
        from db.models.task_dependency import TaskDependencyCreate
        
        parent_id = gen_random_uuid()
        child_id = gen_random_uuid()
        
        data = {
            "parent_task_id": parent_id,
            "child_task_id": child_id,
            "dependency_type": "sequential",
            "condition_json": None,
        }
        model = TaskDependencyCreate(**data)
        
        assert model.parent_task_id == parent_id
        assert model.child_task_id == child_id
        assert model.dependency_type == DependencyType.sequential
        assert model.condition_json is None
    
    def test_dependency_type_string_coercion(self):
        """Test that string values are coerced to DependencyType enum."""
        from db.models.task_dependency import TaskDependencyCreate
        
        parent_id = gen_random_uuid()
        child_id = gen_random_uuid()
        
        # Pass as string - should be coerced
        data = {
            "parent_task_id": parent_id,
            "child_task_id": child_id,
            "dependency_type": "parallel",  # String, not enum
        }
        model = TaskDependencyCreate(**data)
        
        assert model.dependency_type == DependencyType.parallel
        assert isinstance(model.dependency_type, DependencyType)
    
    def test_dependency_type_case_insensitive(self):
        """Test that dependency_type is case-insensitive."""
        from db.models.task_dependency import TaskDependencyCreate
        
        parent_id = gen_random_uuid()
        child_id = gen_random_uuid()
        
        # Upper case
        data = {
            "parent_task_id": parent_id,
            "child_task_id": child_id,
            "dependency_type": "SEQUENTIAL",  # Upper case
        }
        model = TaskDependencyCreate(**data)
        
        assert model.dependency_type == DependencyType.sequential
    
    def test_dependency_type_invalid_raises(self):
        """Test that invalid dependency_type raises validation error."""
        from db.models.task_dependency import TaskDependencyCreate
        from pydantic import ValidationError
        
        parent_id = gen_random_uuid()
        child_id = gen_random_uuid()
        
        data = {
            "parent_task_id": parent_id,
            "child_task_id": child_id,
            "dependency_type": "invalid_type",
        }
        
        with pytest.raises(ValidationError):
            TaskDependencyCreate(**data)
    
    def test_condition_json_accepts_complex_structure(self):
        """Test that condition_json accepts complex nested structures."""
        from db.models.task_dependency import TaskDependencyCreate
        
        parent_id = gen_random_uuid()
        child_id = gen_random_uuid()
        
        condition = {
            "condition": "success",
            "expression": "parent.result.status == 'completed'",
            "fallback": {
                "action": "skip",
                "reason": "Parent failed"
            }
        }
        
        data = {
            "parent_task_id": parent_id,
            "child_task_id": child_id,
            "dependency_type": "conditional",
            "condition_json": condition,
        }
        model = TaskDependencyCreate(**data)
        
        assert model.condition_json == condition
        assert model.condition_json["fallback"]["action"] == "skip"


class TestDependencyTypeEnum:
    """Test DependencyType enum usage."""
    
    async def test_all_enum_values_valid(self, db_session: AsyncSession):
        """Test that all DependencyType enum values are valid."""
        user_id = await _create_test_user(db_session)
        
        for dep_type in DependencyType:
            parent = await _create_test_task(db_session, user_id, f"parent_{dep_type.value}")
            child = await _create_test_task(db_session, user_id, f"child_{dep_type.value}")
            
            dependency = TaskDependency(
                parent_task_id=parent.id,
                child_task_id=child.id,
                dependency_type=dep_type,
            )
            db_session.add(dependency)
            await db_session.commit()
            await db_session.refresh(dependency)
            
            assert dependency.dependency_type == dep_type
    
    def test_enum_serialization(self):
        """Test that DependencyType serializes correctly."""
        assert str(DependencyType.sequential) == "sequential"
        assert DependencyType.sequential.value == "sequential"
        assert not isinstance(DependencyType.sequential.value, int)
        
        assert str(DependencyType.parallel) == "parallel"
        assert str(DependencyType.conditional) == "conditional"


class TestJSONBValidation:
    """Test JSONB field validation for condition_json."""
    
    async def test_condition_json_accepts_dict(self, db_session: AsyncSession):
        """Test that condition_json accepts dictionary."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent")
        child = await _create_test_task(db_session, user_id, "child")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            condition_json={"key": "value", "nested": {"inner": True}},
        )
        db_session.add(dependency)
        await db_session.commit()
        await db_session.refresh(dependency)
        
        assert isinstance(dependency.condition_json, dict)
        assert dependency.condition_json["key"] == "value"
        assert dependency.condition_json["nested"]["inner"] is True
    
    async def test_condition_json_nullable(self, db_session: AsyncSession):
        """Test that condition_json is nullable."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent")
        child = await _create_test_task(db_session, user_id, "child")
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            condition_json=None,
        )
        db_session.add(dependency)
        await db_session.commit()
        await db_session.refresh(dependency)
        
        assert dependency.condition_json is None
    
    async def test_condition_json_complex_structure(self, db_session: AsyncSession):
        """Test that condition_json accepts complex nested structures."""
        user_id = await _create_test_user(db_session)
        
        parent = await _create_test_task(db_session, user_id, "parent")
        child = await _create_test_task(db_session, user_id, "child")
        
        complex_condition = {
            "conditions": [
                {"field": "status", "operator": "==", "value": "completed"},
                {"field": "result.score", "operator": ">=", "value": 0.8}
            ],
            "logic": "AND",
            "fallback": {
                "action": "notify",
                "recipients": ["user1", "user2"]
            }
        }
        
        dependency = TaskDependency(
            parent_task_id=parent.id,
            child_task_id=child.id,
            dependency_type=DependencyType.conditional,
            condition_json=complex_condition,
        )
        db_session.add(dependency)
        await db_session.commit()
        await db_session.refresh(dependency)
        
        assert isinstance(dependency.condition_json, dict)
        assert len(dependency.condition_json["conditions"]) == 2
        assert dependency.condition_json["logic"] == "AND"