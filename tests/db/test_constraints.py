# pyright: reportMissingImports=false
"""
Comprehensive constraint tests for the agent-server database schema.

This module tests all database constraints across all tables:
- Foreign Key constraints (CASCADE, SET NULL behaviors)
- CHECK constraints (enum validation, numeric ranges)
- UNIQUE constraints (single column and composite)

All constraints are validated at the database level to ensure data integrity.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.schema.agents import AgentType, AgentInstance
from db.schema.agent_capabilities import AgentCapability
from db.schema.collaboration import (
    CollaborationSession,
    AgentMessage,
    CollaborationStatus,
    MessageType,
    MessageRedactionLevel,
)
from db.schema.tasks import Task
from db.schema.task_queue import TaskQueue
from db.schema.task_dependencies import TaskDependency
from db.schema.task_schedules import TaskSchedule
from db.schema.dead_letter_queue import DeadLetterQueue
from db.schema.tools import Tool, ToolVersion
from db.schema.tool_calls import ToolCall
from db.schema.token_usage import TokenUsage
from db.schema.users import User
from db.types import (
    AgentStatus,
    TaskStatus,
    Priority,
    DependencyType,
    ScheduleType,
    ActorType,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with all system tables."""
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432')
    db_user = os.getenv('POSTGRES_USER', 'agentserver')
    db_password = os.getenv('POSTGRES_PASSWORD', 'testpass')
    db_name = os.getenv('POSTGRES_DB', 'agentserver')
    
    dsn = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    engine = create_engine(dsn=dsn)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        
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
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_capabilities (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_type_id UUID NOT NULL REFERENCES agent_types(id) ON DELETE CASCADE,
                capability_name TEXT NOT NULL,
                description TEXT,
                input_schema JSONB,
                output_schema JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS collaboration_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                main_agent_id UUID NOT NULL REFERENCES agent_instances(id) ON DELETE CASCADE,
                name TEXT,
                session_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'completed', 'failed', 'cancelled')),
                involves_secrets BOOLEAN NOT NULL DEFAULT false,
                context_json JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                ended_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                collaboration_id UUID NOT NULL REFERENCES collaboration_sessions(id) ON DELETE CASCADE,
                step_id TEXT,
                sender_agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                receiver_agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                message_type TEXT NOT NULL DEFAULT 'request'
                    CHECK (message_type IN ('request', 'response', 'notification', 'ack', 'tool_call', 'tool_result')),
                content_json JSONB NOT NULL,
                redaction_level TEXT NOT NULL DEFAULT 'none'
                    CHECK (redaction_level IN ('none', 'partial', 'full')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
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
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_tasks_retry_count CHECK (retry_count >= 0),
                CONSTRAINT ck_tasks_max_retries CHECK (max_retries >= 0)
            )
        """))
        
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
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_schedules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_template_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                schedule_type TEXT NOT NULL DEFAULT 'cron'
                    CHECK (schedule_type IN ('once', 'interval', 'cron')),
                schedule_expression TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                next_run_at TIMESTAMPTZ,
                last_run_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_task_schedules_template UNIQUE (task_template_id)
            )
        """))
        
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
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tools (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tool_versions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                version TEXT NOT NULL,
                input_schema JSONB,
                output_schema JSONB,
                implementation_ref TEXT,
                config_json JSONB,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                tool_version_id UUID REFERENCES tool_versions(id) ON DELETE SET NULL,
                input JSONB,
                output JSONB,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
                error_message TEXT,
                duration_ms INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_tool_calls_duration_ms CHECK (duration_ms >= 0)
            )
        """))
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID NOT NULL REFERENCES agent_instances(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                estimated_cost_usd NUMERIC(10, 6) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
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
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit.audit_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID,
                actor_type TEXT NOT NULL
                    CHECK (actor_type IN ('user', 'agent', 'system')),
                actor_id UUID NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id UUID NOT NULL,
                old_values JSONB,
                new_values JSONB,
                ip_address INET,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create indexes
        await _create_indexes(conn)
    
    async with async_session_maker() as session:
        yield session
        await session.rollback()
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS audit.audit_log"))
        await conn.execute(text("DROP TABLE IF EXISTS dead_letter_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS token_usage"))
        await conn.execute(text("DROP TABLE IF EXISTS tool_calls"))
        await conn.execute(text("DROP TABLE IF EXISTS tool_versions"))
        await conn.execute(text("DROP TABLE IF EXISTS tools"))
        await conn.execute(text("DROP TABLE IF EXISTS task_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS task_schedules"))
        await conn.execute(text("DROP TABLE IF EXISTS task_dependencies"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_messages"))
        await conn.execute(text("DROP TABLE IF EXISTS collaboration_sessions"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_capabilities"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
        await conn.execute(text("DROP SCHEMA IF EXISTS audit"))
    
    await engine.dispose()


async def _create_indexes(conn) -> None:
    """Create all indexes for the test tables."""
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_types_name ON agent_types(name)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_instances_user ON agent_instances(user_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_capabilities_type ON agent_capabilities(agent_type_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_user ON collaboration_sessions(user_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_collab ON agent_messages(collaboration_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_deps_parent ON task_dependencies(parent_task_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_deps_child ON task_dependencies(child_task_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tool_versions_tool_id ON tool_versions(tool_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_token_usage_user_created ON token_usage(user_id, created_at)"))


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user for testing."""
    user = User(
        username=f"constraint_test_{uuid4().hex[:8]}",
        email=f"constraint_test_{uuid4().hex[:8]}@example.com",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_agent_type(db_session: AsyncSession) -> AgentType:
    """Create a sample agent type for testing."""
    agent_type = AgentType(
        name=f"ConstraintTestAgent_{uuid4().hex[:8]}",
        description="Agent type for constraint testing",
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


@pytest_asyncio.fixture
async def sample_tool(db_session: AsyncSession) -> Tool:
    """Create a sample tool for testing."""
    tool = Tool(
        name=f"constraint_tool_{uuid4().hex[:8]}",
        description="Tool for constraint testing",
        is_active=True,
    )
    db_session.add(tool)
    await db_session.commit()
    await db_session.refresh(tool)
    return tool


# ============================================================================
# FOREIGN KEY CONSTRAINT TESTS
# ============================================================================

class TestForeignKeyConstraints:
    """Test all foreign key constraints across the database schema."""
    
    # -------------------------------------------------------------------------
    # Agent Instance FK Tests
    # -------------------------------------------------------------------------
    
    async def test_agent_instance_requires_valid_agent_type(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that agent_instance cannot be created with invalid agent_type_id."""
        fake_type_id = uuid4()
        agent = AgentInstance(
            agent_type_id=fake_type_id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_agent_instance_requires_valid_user(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that agent_instance cannot be created with invalid user_id."""
        fake_user_id = uuid4()
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=fake_user_id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_agent_instance_cascade_on_user_delete(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that deleting user cascades to agent_instances."""
        user = User(
            username=f"cascade_user_{uuid4().hex[:8]}",
            email=f"cascade_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        agent_id = agent.id
        user_id = user.id
        
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user_id}'")
        )
        await db_session.commit()
        
        # Verify agent was cascade deleted
        result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.id == agent_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_agent_instance_cascade_on_agent_type_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that deleting agent_type cascades to agent_instances."""
        agent_type = AgentType(
            name=f"CascadeType_{uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        agent_id = agent.id
        
        # Delete agent type
        await db_session.delete(agent_type)
        await db_session.commit()
        
        # Verify agent was cascade deleted
        result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.id == agent_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Agent Capability FK Tests
    # -------------------------------------------------------------------------
    
    async def test_agent_capability_requires_valid_agent_type(
        self,
        db_session: AsyncSession,
    ):
        """Test that capability cannot be created with invalid agent_type_id."""
        fake_type_id = uuid4()
        cap = AgentCapability(
            agent_type_id=fake_type_id,
            capability_name="test_capability",
        )
        db_session.add(cap)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_agent_capability_cascade_on_agent_type_delete(
        self,
        db_session: AsyncSession,
    ):
        """Test that deleting agent_type cascades to capabilities."""
        agent_type = AgentType(
            name=f"CapType_{uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        cap = AgentCapability(
            agent_type_id=agent_type.id,
            capability_name="test_cap",
        )
        db_session.add(cap)
        await db_session.commit()
        await db_session.refresh(cap)
        
        cap_id = cap.id
        
        # Delete agent type
        await db_session.delete(agent_type)
        await db_session.commit()
        
        # Verify capability was cascade deleted
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.id == cap_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Task FK Tests
    # -------------------------------------------------------------------------
    
    async def test_task_requires_valid_user(
        self,
        db_session: AsyncSession,
    ):
        """Test that task cannot be created with invalid user_id."""
        fake_user_id = uuid4()
        task = Task(
            user_id=fake_user_id,
            task_type="test_task",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_task_set_null_on_agent_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that deleting agent sets task.agent_id to NULL."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            task_type="test_task",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        task_id = task.id
        
        # Delete agent
        await db_session.delete(agent)
        await db_session.commit()
        
        # Verify task still exists with NULL agent_id
        result = await db_session.execute(
            select(Task).where(Task.id == task_id)
        )
        saved_task = result.scalar_one()
        assert saved_task is not None
        assert saved_task.agent_id is None
    
    async def test_task_cascade_on_user_delete(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that deleting user cascades to tasks."""
        user = User(
            username=f"task_cascade_{uuid4().hex[:8]}",
            email=f"task_cascade_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        task = Task(
            user_id=user.id,
            task_type="cascade_test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        task_id = task.id
        
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user.id}'")
        )
        await db_session.commit()
        
        # Verify task was cascade deleted
        result = await db_session.execute(
            select(Task).where(Task.id == task_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_parent_task_cascade_deletes_children(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that deleting parent task cascades to child tasks."""
        parent = Task(
            user_id=sample_user.id,
            task_type="parent_task",
            status=TaskStatus.pending,
        )
        db_session.add(parent)
        await db_session.commit()
        await db_session.refresh(parent)
        
        child = Task(
            user_id=sample_user.id,
            parent_task_id=parent.id,
            task_type="child_task",
            status=TaskStatus.pending,
        )
        db_session.add(child)
        await db_session.commit()
        await db_session.refresh(child)
        
        child_id = child.id
        
        # Delete parent
        await db_session.delete(parent)
        await db_session.commit()
        
        # Verify child was cascade deleted
        result = await db_session.execute(
            select(Task).where(Task.id == child_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Task Dependency FK Tests
    # -------------------------------------------------------------------------
    
    async def test_task_dependency_requires_valid_parent(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that dependency cannot be created with invalid parent_task_id."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        fake_parent_id = uuid4()
        dep = TaskDependency(
            parent_task_id=fake_parent_id,
            child_task_id=task.id,
        )
        db_session.add(dep)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_task_dependency_requires_valid_child(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that dependency cannot be created with invalid child_task_id."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        fake_child_id = uuid4()
        dep = TaskDependency(
            parent_task_id=task.id,
            child_task_id=fake_child_id,
        )
        db_session.add(dep)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_task_dependency_cascade_on_task_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that deleting task cascades to related dependencies."""
        task1 = Task(
            user_id=sample_user.id,
            task_type="task1",
            status=TaskStatus.pending,
        )
        task2 = Task(
            user_id=sample_user.id,
            task_type="task2",
            status=TaskStatus.pending,
        )
        db_session.add_all([task1, task2])
        await db_session.commit()
        for t in [task1, task2]:
            await db_session.refresh(t)
        
        dep = TaskDependency(
            parent_task_id=task1.id,
            child_task_id=task2.id,
        )
        db_session.add(dep)
        await db_session.commit()
        await db_session.refresh(dep)
        
        dep_id = dep.id
        
        # Delete one task
        await db_session.delete(task1)
        await db_session.commit()
        
        # Verify dependency was cascade deleted
        result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.id == dep_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Collaboration Session FK Tests
    # -------------------------------------------------------------------------
    
    async def test_collaboration_requires_valid_user(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
        sample_user: User,
    ):
        """Test that collaboration cannot be created with invalid user_id."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        fake_user_id = uuid4()
        collab = CollaborationSession(
            user_id=fake_user_id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_collaboration_requires_valid_agent(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that collaboration cannot be created with invalid main_agent_id."""
        fake_agent_id = uuid4()
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=fake_agent_id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_collaboration_cascade_on_user_delete(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that deleting user cascades to collaboration_sessions."""
        user = User(
            username=f"collab_cascade_{uuid4().hex[:8]}",
            email=f"collab_cascade_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        collab = CollaborationSession(
            user_id=user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        collab_id = collab.id
        
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user.id}'")
        )
        await db_session.commit()
        
        # Verify collaboration was cascade deleted
        result = await db_session.execute(
            select(CollaborationSession).where(CollaborationSession.id == collab_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Agent Message FK Tests
    # -------------------------------------------------------------------------
    
    async def test_message_requires_valid_collaboration(
        self,
        db_session: AsyncSession,
    ):
        """Test that message cannot be created with invalid collaboration_id."""
        fake_collab_id = uuid4()
        msg = AgentMessage(
            collaboration_id=fake_collab_id,
            message_type=MessageType.request,
            content_json={"test": "data"},
        )
        db_session.add(msg)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_message_sender_set_null_on_agent_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that deleting sender agent sets sender_agent_id to NULL."""
        main_agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        sender_agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add_all([main_agent, sender_agent])
        await db_session.commit()
        for a in [main_agent, sender_agent]:
            await db_session.refresh(a)
        
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=main_agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        msg = AgentMessage(
            collaboration_id=collab.id,
            sender_agent_id=sender_agent.id,
            message_type=MessageType.request,
            content_json={"test": "data"},
        )
        db_session.add(msg)
        await db_session.commit()
        await db_session.refresh(msg)
        
        msg_id = msg.id
        sender_id = sender_agent.id
        
        # Delete sender agent
        await db_session.delete(sender_agent)
        await db_session.commit()
        
        # Verify message still exists with NULL sender_agent_id
        result = await db_session.execute(
            text(f"SELECT sender_agent_id FROM agent_messages WHERE id = '{msg_id}'")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] is None
    
    async def test_message_cascade_on_collaboration_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that deleting collaboration cascades to messages."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        msg = AgentMessage(
            collaboration_id=collab.id,
            message_type=MessageType.request,
            content_json={"test": "data"},
        )
        db_session.add(msg)
        await db_session.commit()
        await db_session.refresh(msg)
        
        msg_id = msg.id
        
        # Delete collaboration
        await db_session.delete(collab)
        await db_session.commit()
        
        # Verify message was cascade deleted
        result = await db_session.execute(
            select(AgentMessage).where(AgentMessage.id == msg_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Tool Call FK Tests
    # -------------------------------------------------------------------------
    
    async def test_tool_call_requires_valid_task(
        self,
        db_session: AsyncSession,
        sample_tool: Tool,
    ):
        """Test that tool_call cannot be created with invalid task_id."""
        fake_task_id = uuid4()
        tool_call = ToolCall(
            task_id=fake_task_id,
            tool_id=sample_tool.id,
            status="pending",
        )
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_tool_call_requires_valid_tool(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that tool_call cannot be created with invalid tool_id."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        fake_tool_id = uuid4()
        tool_call = ToolCall(
            task_id=task.id,
            tool_id=fake_tool_id,
            status="pending",
        )
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_tool_call_cascade_on_task_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_tool: Tool,
    ):
        """Test that deleting task cascades to tool_calls."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        tool_call = ToolCall(
            task_id=task.id,
            tool_id=sample_tool.id,
            status="pending",
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        tc_id = tool_call.id
        
        # Delete task
        await db_session.delete(task)
        await db_session.commit()
        
        # Verify tool_call was cascade deleted
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tc_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_tool_call_set_null_on_version_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_tool: Tool,
    ):
        """Test that deleting tool_version sets tool_version_id to NULL."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        version = ToolVersion(
            tool_id=sample_tool.id,
            version="1.0.0",
            is_default=True,
        )
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)
        
        tool_call = ToolCall(
            task_id=task.id,
            tool_id=sample_tool.id,
            tool_version_id=version.id,
            status="pending",
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        tc_id = tool_call.id
        
        # Delete version
        await db_session.delete(version)
        await db_session.commit()
        
        # Verify tool_call still exists with NULL tool_version_id
        result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tc_id)
        )
        saved_tc = result.scalar_one()
        assert saved_tc is not None
        assert saved_tc.tool_version_id is None
    
    # -------------------------------------------------------------------------
    # Token Usage FK Tests
    # -------------------------------------------------------------------------
    
    async def test_token_usage_requires_valid_user(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
        sample_user: User,
    ):
        """Test that token_usage cannot be created with invalid user_id."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        fake_user_id = uuid4()
        tu = TokenUsage(
            user_id=fake_user_id,
            agent_id=agent.id,
            session_id="test-session",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.01"),
        )
        db_session.add(tu)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_token_usage_requires_valid_agent(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that token_usage cannot be created with invalid agent_id."""
        fake_agent_id = uuid4()
        tu = TokenUsage(
            user_id=sample_user.id,
            agent_id=fake_agent_id,
            session_id="test-session",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.01"),
        )
        db_session.add(tu)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_token_usage_cascade_on_user_delete(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that deleting user cascades to token_usage."""
        user = User(
            username=f"tu_cascade_{uuid4().hex[:8]}",
            email=f"tu_cascade_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        tu = TokenUsage(
            user_id=user.id,
            agent_id=agent.id,
            session_id="test-session",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.01"),
        )
        db_session.add(tu)
        await db_session.commit()
        await db_session.refresh(tu)
        
        tu_id = tu.id
        
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user.id}'")
        )
        await db_session.commit()
        
        # Verify token_usage was cascade deleted
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.id == tu_id)
        )
        assert result.scalar_one_or_none() is None
    
    # -------------------------------------------------------------------------
    # Queue Entry FK Tests
    # -------------------------------------------------------------------------
    
    async def test_queue_entry_requires_valid_task(
        self,
        db_session: AsyncSession,
    ):
        """Test that queue entry cannot be created with invalid task_id."""
        fake_task_id = uuid4()
        queue_entry = TaskQueue(
            task_id=fake_task_id,
            status=TaskStatus.pending,
            priority=5,
        )
        db_session.add(queue_entry)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_queue_claimed_by_set_null_on_agent_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that deleting agent sets queue.claimed_by to NULL."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.running,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.running,
            claimed_by=agent.id,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        queue_id = queue_entry.id
        
        # Delete agent
        await db_session.delete(agent)
        await db_session.commit()
        
        # Verify queue entry still exists with NULL claimed_by
        result = await db_session.execute(
            select(TaskQueue).where(TaskQueue.id == queue_id)
        )
        saved_queue = result.scalar_one()
        assert saved_queue is not None
        assert saved_queue.claimed_by is None
    
    # -------------------------------------------------------------------------
    # DLQ FK Tests
    # -------------------------------------------------------------------------
    
    async def test_dlq_original_task_set_null_on_task_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that deleting task sets DLQ.original_task_id to NULL."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.failed,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        dlq = DeadLetterQueue(
            original_task_id=task.id,
            original_payload_json={"test": "data"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            is_active=True,
        )
        db_session.add(dlq)
        await db_session.commit()
        await db_session.refresh(dlq)
        
        dlq_id = dlq.id
        
        # Delete task
        await db_session.delete(task)
        await db_session.commit()
        
        # Verify DLQ still exists with NULL original_task_id
        result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.id == dlq_id)
        )
        saved_dlq = result.scalar_one()
        assert saved_dlq is not None
        assert saved_dlq.original_task_id is None


# ============================================================================
# CHECK CONSTRAINT TESTS
# ============================================================================

class TestCheckConstraints:
    """Test all CHECK constraints across the database schema."""
    
    # -------------------------------------------------------------------------
    # Agent Instance Status CHECK
    # -------------------------------------------------------------------------
    
    async def test_agent_status_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that agent status accepts valid values."""
        for status in [AgentStatus.idle, AgentStatus.busy, AgentStatus.error, AgentStatus.offline]:
            agent = AgentInstance(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                status=status,
            )
            db_session.add(agent)
            await db_session.commit()
            await db_session.refresh(agent)
            assert agent.status == status
            await db_session.delete(agent)
            await db_session.commit()
    
    async def test_agent_status_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that invalid agent status is rejected."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Try to set invalid status via raw SQL
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE agent_instances SET status = 'invalid_status' WHERE id = '{agent.id}'")
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Task Status CHECK
    # -------------------------------------------------------------------------
    
    async def test_task_status_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that task status accepts valid values."""
        for status in [TaskStatus.pending, TaskStatus.running, TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled]:
            task = Task(
                user_id=sample_user.id,
                task_type=f"test_{status.value}",
                status=status,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            assert task.status == status
            await db_session.delete(task)
            await db_session.commit()
    
    async def test_task_status_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that invalid task status is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET status = 'invalid_status' WHERE id = '{task.id}'")
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Task Priority CHECK
    # -------------------------------------------------------------------------
    
    async def test_task_priority_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that task priority accepts valid values."""
        for priority in [Priority.low, Priority.normal, Priority.high, Priority.critical]:
            task = Task(
                user_id=sample_user.id,
                task_type=f"test_{priority.value}",
                priority=priority,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            assert task.priority == priority
            await db_session.delete(task)
            await db_session.commit()
    
    async def test_task_priority_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that invalid task priority is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            priority=Priority.normal,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET priority = 'invalid_priority' WHERE id = '{task.id}'")
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Task Retry Count CHECK
    # -------------------------------------------------------------------------
    
    async def test_task_retry_count_negative_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that negative retry_count is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            retry_count=0,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET retry_count = -1 WHERE id = '{task.id}'")
            )
            await db_session.commit()
    
    async def test_task_max_retries_negative_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that negative max_retries is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="test",
            max_retries=3,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET max_retries = -1 WHERE id = '{task.id}'")
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Task Dependency Type CHECK
    # -------------------------------------------------------------------------
    
    async def test_dependency_type_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that dependency type accepts valid values."""
        task1 = Task(
            user_id=sample_user.id,
            task_type="task1",
        )
        task2 = Task(
            user_id=sample_user.id,
            task_type="task2",
        )
        db_session.add_all([task1, task2])
        await db_session.commit()
        for t in [task1, task2]:
            await db_session.refresh(t)
        
        for dep_type in [DependencyType.sequential, DependencyType.parallel, DependencyType.conditional]:
            dep = TaskDependency(
                parent_task_id=task1.id,
                child_task_id=task2.id,
                dependency_type=dep_type,
            )
            db_session.add(dep)
            await db_session.commit()
            await db_session.refresh(dep)
            assert dep.dependency_type == dep_type
            await db_session.delete(dep)
            await db_session.commit()
    
    async def test_dependency_type_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that invalid dependency type is rejected."""
        task1 = Task(
            user_id=sample_user.id,
            task_type="task1",
        )
        task2 = Task(
            user_id=sample_user.id,
            task_type="task2",
        )
        db_session.add_all([task1, task2])
        await db_session.commit()
        for t in [task1, task2]:
            await db_session.refresh(t)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"""
                    INSERT INTO task_dependencies (parent_task_id, child_task_id, dependency_type)
                    VALUES ('{task1.id}', '{task2.id}', 'invalid_type')
                """)
            )
            await db_session.commit()
    
    async def test_dependency_self_reference_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that self-referencing dependency is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="self_ref_test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"""
                    INSERT INTO task_dependencies (parent_task_id, child_task_id)
                    VALUES ('{task.id}', '{task.id}')
                """)
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Schedule Type CHECK
    # -------------------------------------------------------------------------
    
    async def test_schedule_type_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that schedule type accepts valid values."""
        for sched_type in [ScheduleType.once, ScheduleType.interval, ScheduleType.cron]:
            task = Task(
                user_id=sample_user.id,
                task_type=f"sched_test_{sched_type.value}",
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)
            
            schedule = TaskSchedule(
                task_template_id=task.id,
                schedule_type=sched_type,
                schedule_expression="* * * * *" if sched_type == ScheduleType.cron else "PT5M",
            )
            db_session.add(schedule)
            await db_session.commit()
            assert schedule.schedule_type == sched_type
    
    async def test_schedule_type_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that invalid schedule type is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="sched_test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"""
                    INSERT INTO task_schedules (task_template_id, schedule_type, schedule_expression)
                    VALUES ('{task.id}', 'invalid_type', 'test')
                """)
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Tool Call Status CHECK
    # -------------------------------------------------------------------------
    
    async def test_tool_call_status_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_tool: Tool,
    ):
        """Test that tool call status accepts valid values."""
        task = Task(
            user_id=sample_user.id,
            task_type="tool_test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        for status in ["pending", "running", "completed", "failed"]:
            tc = ToolCall(
                task_id=task.id,
                tool_id=sample_tool.id,
                status=status,
            )
            db_session.add(tc)
            await db_session.commit()
            await db_session.refresh(tc)
            assert tc.status == status
            await db_session.delete(tc)
            await db_session.commit()
    
    async def test_tool_call_status_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_tool: Tool,
    ):
        """Test that invalid tool call status is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="tool_test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"""
                    INSERT INTO tool_calls (task_id, tool_id, status)
                    VALUES ('{task.id}', '{sample_tool.id}', 'invalid_status')
                """)
            )
            await db_session.commit()
    
    async def test_tool_call_duration_negative_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_tool: Tool,
    ):
        """Test that negative duration_ms is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="tool_test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        tc = ToolCall(
            task_id=task.id,
            tool_id=sample_tool.id,
            status="completed",
            duration_ms=100,
        )
        db_session.add(tc)
        await db_session.commit()
        await db_session.refresh(tc)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tool_calls SET duration_ms = -1 WHERE id = '{tc.id}'")
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Collaboration Status CHECK
    # -------------------------------------------------------------------------
    
    async def test_collaboration_status_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that collaboration status accepts valid values."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        for status in [CollaborationStatus.active, CollaborationStatus.completed, CollaborationStatus.failed, CollaborationStatus.cancelled]:
            collab = CollaborationSession(
                user_id=sample_user.id,
                main_agent_id=agent.id,
                session_id=f"session-{uuid4()}",
                status=status,
            )
            db_session.add(collab)
            await db_session.commit()
            await db_session.refresh(collab)
            assert collab.status == status
            await db_session.delete(collab)
            await db_session.commit()
    
    async def test_collaboration_status_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that invalid collaboration status is rejected."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE collaboration_sessions SET status = 'invalid_status' WHERE id = '{collab.id}'")
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Message Type CHECK
    # -------------------------------------------------------------------------
    
    async def test_message_type_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that message type accepts valid values."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        for msg_type in [MessageType.request, MessageType.response, MessageType.notification, MessageType.ack, MessageType.tool_call, MessageType.tool_result]:
            msg = AgentMessage(
                collaboration_id=collab.id,
                message_type=msg_type,
                content_json={"test": "data"},
            )
            db_session.add(msg)
            await db_session.commit()
            await db_session.refresh(msg)
            assert msg.message_type == msg_type
            await db_session.delete(msg)
            await db_session.commit()
    
    async def test_message_type_invalid_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that invalid message type is rejected."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"""
                    INSERT INTO agent_messages (collaboration_id, message_type, content_json)
                    VALUES ('{collab.id}', 'invalid_type', '{{}}')
                """)
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Queue Priority CHECK
    # -------------------------------------------------------------------------
    
    async def test_queue_priority_negative_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that negative queue priority is rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="queue_test",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"""
                    INSERT INTO task_queue (task_id, status, priority)
                    VALUES ('{task.id}', 'pending', -1)
                """)
            )
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Audit Actor Type CHECK
    # -------------------------------------------------------------------------
    
    async def test_audit_actor_type_valid_values(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that audit actor_type accepts valid values."""
        for actor_type in [ActorType.user, ActorType.agent, ActorType.system]:
            result = await db_session.execute(
                text("""
                    INSERT INTO audit.audit_log 
                    (user_id, actor_type, actor_id, action, resource_type, resource_id)
                    VALUES (:user_id, :actor_type, :actor_id, 'test', 'test', :resource_id)
                    RETURNING id
                """),
                {
                    "user_id": str(sample_user.id),
                    "actor_type": actor_type.value,
                    "actor_id": str(uuid4()),
                    "resource_id": str(uuid4()),
                },
            )
            assert result.scalar() is not None
            await db_session.commit()
    
    async def test_audit_actor_type_invalid_rejected(
        self,
        db_session: AsyncSession,
    ):
        """Test that invalid audit actor_type is rejected."""
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text("""
                    INSERT INTO audit.audit_log 
                    (actor_type, actor_id, action, resource_type, resource_id)
                    VALUES ('invalid_type', :actor_id, 'test', 'test', :resource_id)
                """),
                {"actor_id": str(uuid4()), "resource_id": str(uuid4())},
            )
            await db_session.commit()


# ============================================================================
# UNIQUE CONSTRAINT TESTS
# ============================================================================

class TestUniqueConstraints:
    """Test all UNIQUE constraints across the database schema."""
    
    # -------------------------------------------------------------------------
    # Users Table
    # -------------------------------------------------------------------------
    
    async def test_user_username_unique(
        self,
        db_session: AsyncSession,
    ):
        """Test that duplicate username is rejected."""
        username = f"unique_user_{uuid4().hex[:8]}"
        
        user1 = User(
            username=username,
            email=f"user1_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user1)
        await db_session.commit()
        
        user2 = User(
            username=username,  # Duplicate
            email=f"user2_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_user_email_unique(
        self,
        db_session: AsyncSession,
    ):
        """Test that duplicate email is rejected."""
        email = f"unique_{uuid4().hex[:8]}@example.com"
        
        user1 = User(
            username=f"user1_{uuid4().hex[:8]}",
            email=email,
        )
        db_session.add(user1)
        await db_session.commit()
        
        user2 = User(
            username=f"user2_{uuid4().hex[:8]}",
            email=email,  # Duplicate
        )
        db_session.add(user2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Agent Types Table
    # -------------------------------------------------------------------------
    
    async def test_agent_type_name_unique(
        self,
        db_session: AsyncSession,
    ):
        """Test that duplicate agent_type name is rejected."""
        name = f"UniqueAgent_{uuid4().hex[:8]}"
        
        type1 = AgentType(name=name, is_active=True)
        db_session.add(type1)
        await db_session.commit()
        
        type2 = AgentType(name=name, is_active=True)  # Duplicate
        db_session.add(type2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Collaboration Sessions Table
    # -------------------------------------------------------------------------
    
    async def test_collaboration_session_id_unique(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that duplicate collaboration session_id is rejected."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        session_id = f"session-{uuid4()}"
        
        collab1 = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=session_id,
        )
        db_session.add(collab1)
        await db_session.commit()
        
        collab2 = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=session_id,  # Duplicate
        )
        db_session.add(collab2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Task Dependencies Table
    # -------------------------------------------------------------------------
    
    async def test_task_dependency_composite_unique(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that duplicate parent-child dependency is rejected."""
        task1 = Task(
            user_id=sample_user.id,
            task_type="task1",
        )
        task2 = Task(
            user_id=sample_user.id,
            task_type="task2",
        )
        db_session.add_all([task1, task2])
        await db_session.commit()
        for t in [task1, task2]:
            await db_session.refresh(t)
        
        dep1 = TaskDependency(
            parent_task_id=task1.id,
            child_task_id=task2.id,
        )
        db_session.add(dep1)
        await db_session.commit()
        
        dep2 = TaskDependency(
            parent_task_id=task1.id,
            child_task_id=task2.id,  # Duplicate combination
        )
        db_session.add(dep2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_task_dependency_different_pairs_allowed(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that different parent-child pairs are allowed."""
        task1 = Task(user_id=sample_user.id, task_type="task1")
        task2 = Task(user_id=sample_user.id, task_type="task2")
        task3 = Task(user_id=sample_user.id, task_type="task3")
        db_session.add_all([task1, task2, task3])
        await db_session.commit()
        for t in [task1, task2, task3]:
            await db_session.refresh(t)
        
        # task1 -> task2
        dep1 = TaskDependency(parent_task_id=task1.id, child_task_id=task2.id)
        # task1 -> task3 (different child)
        dep2 = TaskDependency(parent_task_id=task1.id, child_task_id=task3.id)
        # task2 -> task3 (different parent)
        dep3 = TaskDependency(parent_task_id=task2.id, child_task_id=task3.id)
        
        db_session.add_all([dep1, dep2, dep3])
        await db_session.commit()
        
        # Verify all were created
        result = await db_session.execute(select(TaskDependency))
        deps = result.scalars().all()
        assert len(deps) == 3
    
    # -------------------------------------------------------------------------
    # Task Schedules Table
    # -------------------------------------------------------------------------
    
    async def test_task_schedule_template_unique(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that only one schedule per task template is allowed."""
        task = Task(
            user_id=sample_user.id,
            task_type="scheduled_task",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        schedule1 = TaskSchedule(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 9 * * *",
        )
        db_session.add(schedule1)
        await db_session.commit()
        
        schedule2 = TaskSchedule(
            task_template_id=task.id,  # Duplicate
            schedule_type=ScheduleType.interval,
            schedule_expression="PT1H",
        )
        db_session.add(schedule2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    # -------------------------------------------------------------------------
    # Tools Table
    # -------------------------------------------------------------------------
    
    async def test_tool_name_unique(
        self,
        db_session: AsyncSession,
    ):
        """Test that duplicate tool name is rejected."""
        name = f"unique_tool_{uuid4().hex[:8]}"
        
        tool1 = Tool(name=name, is_active=True)
        db_session.add(tool1)
        await db_session.commit()
        
        tool2 = Tool(name=name, is_active=True)  # Duplicate
        db_session.add(tool2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()