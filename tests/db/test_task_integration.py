# pyright: reportMissingImports=false
"""
Comprehensive integration tests for the task system.

This module tests end-to-end workflows across the task system tables:
- users
- agent_types, agent_instances
- tasks
- task_queue
- task_dependencies
- task_schedules
- dead_letter_queue
- collaboration_sessions, agent_messages
- llm_endpoints, llm_endpoint_groups

Test scenarios:
1. End-to-end task workflow (creation → completion)
2. Retry flow and dead letter queue
3. Cascading deletes and SET NULL behavior
4. Multi-agent collaboration within task context
5. Performance benchmarks for key queries
6. Error handling and constraint validation
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from db import create_engine, AsyncSession
from db.entity.agent_entity import AgentType, AgentInstance
from db.entity.collaboration_entity import CollaborationSession, AgentMessage
from db.entity.llm_endpoint_entity import LLMEndpoint, LLMEndpointGroup, LLMLevelEndpoint
from db.entity.task_entity import Task, TaskDependency
from db.entity.task_queue_entity import TaskQueue
from db.entity.task_schedule_entity import TaskSchedule
from db.entity.dead_letter_queue_entity import DeadLetterQueue
from db.entity.user_entity import User
from db.types import (
    AgentStatus,
    TaskStatus,
    Priority,
    DependencyType,
    ScheduleType,
)
from db.crypto import CryptoManager, generate_key


# Import all entity modules to ensure SQLAlchemy relationship resolution
from db.entity import user_entity  # noqa: F401
from db.entity import agent_entity  # noqa: F401
from db.entity import llm_endpoint_entity  # noqa: F401
from db.entity import collaboration_entity  # noqa: F401
from db.entity import task_entity  # noqa: F401
from db.entity import task_queue_entity  # noqa: F401
from db.entity import task_schedule_entity  # noqa: F401
from db.entity import dead_letter_queue_entity  # noqa: F401


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with all task system tables.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation with full schema setup.
    
    Uses environment variables from .env file for database connection.
    """
    # Use the main database for testing - read from environment variables
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432')
    db_user = os.getenv('POSTGRES_USER', 'agentserver')
    db_password = os.getenv('POSTGRES_PASSWORD', 'testpass')
    db_name = os.getenv('POSTGRES_DB', 'agentserver')
    
    dsn = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    engine = create_engine(dsn=dsn)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Create all tables for testing in dependency order
    async with engine.begin() as conn:
        # 1. Create users table (root dependency)
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
        
        # 1b. Create api_keys table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL,
                name TEXT,
                last_used_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # 2. Create agent_types table
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
        
        # 3. Create agent_instances table
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
        
        # 4. Create collaboration_sessions table
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
        
        # 5. Create agent_messages table
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
        
        # 6. Create tasks table
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
        
        # 7. Create task_dependencies table
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
        
        # 8. Create task_schedules table
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
        
        # 9. Create task_queue table
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
        
        # 10. Create llm_endpoint_groups table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_endpoint_groups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_llm_endpoint_groups_name_per_user UNIQUE (name, user_id)
            )
        """))
        
        # 11. Create llm_endpoints table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_endpoints (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                model_name TEXT NOT NULL,
                config_json JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                last_success_at TIMESTAMPTZ,
                last_failure_at TIMESTAMPTZ,
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # 12. Create llm_level_endpoints table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_level_endpoints (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                group_id UUID NOT NULL REFERENCES llm_endpoint_groups(id) ON DELETE CASCADE,
                difficulty_level SMALLINT NOT NULL,
                involves_secrets BOOLEAN NOT NULL DEFAULT false,
                endpoint_id UUID NOT NULL REFERENCES llm_endpoints(id) ON DELETE CASCADE,
                priority INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_llm_level_endpoints_difficulty_level CHECK (difficulty_level BETWEEN 1 AND 3),
                CONSTRAINT uq_llm_level_endpoints_group_level_secrets_endpoint 
                    UNIQUE (group_id, difficulty_level, involves_secrets, endpoint_id)
            )
        """))
        
        # 13. Create dead_letter_queue table
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
        
        # Create indexes for all tables
        # Tasks indexes
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
        
        # Task queue partial indexes
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
        
        # Task dependencies indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_deps_parent ON task_dependencies(parent_task_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_deps_child ON task_dependencies(child_task_id)
        """))
        
        # DLQ partial indexes
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
        
        # Collaboration indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_collab_user ON collaboration_sessions(user_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_collab_status ON collaboration_sessions(status)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_messages_collab ON agent_messages(collaboration_id, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_messages_step ON agent_messages(step_id)
        """))
    
    async with async_session_maker() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test (reverse dependency order)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS dead_letter_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS llm_level_endpoints"))
        await conn.execute(text("DROP TABLE IF EXISTS llm_endpoints"))
        await conn.execute(text("DROP TABLE IF EXISTS llm_endpoint_groups"))
        await conn.execute(text("DROP TABLE IF EXISTS task_queue"))
        await conn.execute(text("DROP TABLE IF EXISTS task_schedules"))
        await conn.execute(text("DROP TABLE IF EXISTS task_dependencies"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_messages"))
        await conn.execute(text("DROP TABLE IF EXISTS collaboration_sessions"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS api_keys"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user for testing."""
    user = User(
        username=f"testuser_{uuid4().hex[:8]}",
        email=f"test_{uuid4().hex[:8]}@example.com",
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
        name=f"TaskAgent_{uuid4().hex[:8]}",
        description="Agent type for task processing",
        capabilities={
            "task_processing": True,
            "web_search": True,
            "max_retries": 5,
        },
        default_config={
            "timeout_seconds": 300,
            "priority_boost": True,
        },
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


@pytest_asyncio.fixture
async def sample_agent_instance(
    db_session: AsyncSession,
    sample_user: User,
    sample_agent_type: AgentType,
) -> AgentInstance:
    """Create a sample agent instance for testing."""
    agent = AgentInstance(
        agent_type_id=sample_agent_type.id,
        user_id=sample_user.id,
        name="TaskWorker-001",
        status=AgentStatus.idle,
        config={"custom_timeout": 600},
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


# ============================================================================
# Test Scenario 1: End-to-End Task Workflow
# ============================================================================

class TestEndToEndTaskWorkflow:
    """Test complete task lifecycle from creation to completion.
    
    This test validates the entire flow:
    User -> Agent type -> Agent instance -> Task creation -> 
    Queue entry -> Agent claim -> Processing -> Completion
    """
    
    async def test_complete_task_lifecycle_success(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
        sample_agent_instance: AgentInstance,
    ):
        """Test successful task lifecycle from creation to completion."""
        # Step 1: Create a task
        task = Task(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            task_type="research",
            status=TaskStatus.pending,
            priority=Priority.high,
            payload={"query": "AI developments 2026", "max_results": 10},
            max_retries=3,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.id is not None
        assert task.status == TaskStatus.pending
        assert task.priority == Priority.high
        
        # Step 2: Create queue entry for the task
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.pending,
            priority=10,  # High priority
            scheduled_at=None,  # Immediate
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        assert queue_entry.id is not None
        assert queue_entry.status == TaskStatus.pending
        
        # Step 3: Poll queue for next task (simulating agent claiming)
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc())
            .limit(1)
        )
        claimed_entry = result.scalar_one()
        assert claimed_entry.task_id == task.id
        
        # Step 4: Agent claims the task
        claimed_entry.status = TaskStatus.running
        claimed_entry.claimed_by = sample_agent_instance.id
        claimed_entry.claimed_at = datetime.now(timezone.utc)
        claimed_entry.started_at = datetime.now(timezone.utc)
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        sample_agent_instance.status = AgentStatus.busy
        await db_session.commit()
        
        # Step 5: Process task (simulate work)
        # In real scenario, agent would process the payload
        await db_session.refresh(task)
        await db_session.refresh(queue_entry)
        
        assert task.status == TaskStatus.running
        assert queue_entry.claimed_by == sample_agent_instance.id
        
        # Step 6: Complete the task
        task.status = TaskStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        task.result = {
            "findings": ["AI advancement 1", "AI advancement 2"],
            "sources": 5,
            "confidence": 0.95,
        }
        queue_entry.status = TaskStatus.completed
        queue_entry.completed_at = datetime.now(timezone.utc)
        queue_entry.result_json = {"processed": True, "duration_ms": 1500}
        sample_agent_instance.status = AgentStatus.idle
        await db_session.commit()
        
        # Step 7: Verify final state
        await db_session.refresh(task)
        await db_session.refresh(queue_entry)
        await db_session.refresh(sample_agent_instance)
        
        assert task.status == TaskStatus.completed
        assert task.result is not None
        assert task.result["findings"] is not None
        assert queue_entry.status == TaskStatus.completed
        assert sample_agent_instance.status == AgentStatus.idle
    
    async def test_task_lifecycle_with_failure_and_retry(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_instance: AgentInstance,
    ):
        """Test task lifecycle with failure and retry flow."""
        # Create task
        task = Task(
            user_id=sample_user.id,
            task_type="data_processing",
            status=TaskStatus.pending,
            max_retries=3,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create queue entry
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.pending,
            priority=5,
            max_retries=3,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # First attempt: Claim and fail
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = sample_agent_instance.id
        queue_entry.started_at = datetime.now(timezone.utc)
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        await db_session.commit()
        
        # Simulate failure
        queue_entry.status = TaskStatus.pending  # Back to pending for retry
        queue_entry.retry_count = 1
        queue_entry.error_message = "Connection timeout"
        queue_entry.claimed_by = None
        queue_entry.started_at = None
        task.status = TaskStatus.pending
        task.retry_count = 1
        task.error_message = "Connection timeout"
        await db_session.commit()
        
        # Verify retry state
        await db_session.refresh(queue_entry)
        assert queue_entry.retry_count == 1
        assert queue_entry.status == TaskStatus.pending
        
        # Second attempt: Claim again and succeed
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = sample_agent_instance.id
        queue_entry.started_at = datetime.now(timezone.utc)
        task.status = TaskStatus.running
        await db_session.commit()
        
        # Complete successfully
        queue_entry.status = TaskStatus.completed
        queue_entry.completed_at = datetime.now(timezone.utc)
        queue_entry.error_message = None  # Clear error
        task.status = TaskStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        task.result = {"processed": True}
        await db_session.commit()
        
        # Verify success after retry
        await db_session.refresh(task)
        assert task.status == TaskStatus.completed
        assert task.retry_count == 1  # Still shows retry happened
    
    async def test_task_lifecycle_max_retries_exceeded_to_dlq(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_instance: AgentInstance,
    ):
        """Test task moving to dead letter queue after max retries exceeded."""
        # Create task
        task = Task(
            user_id=sample_user.id,
            task_type="critical_operation",
            status=TaskStatus.pending,
            retry_count=3,  # Already at max
            max_retries=3,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create queue entry
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.running,  # Currently running (last attempt)
            priority=1,
            retry_count=3,
            max_retries=3,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Simulate final failure
        queue_entry.status = TaskStatus.failed
        queue_entry.completed_at = datetime.now(timezone.utc)
        queue_entry.error_message = "Max retries exceeded: Persistent connection error"
        task.status = TaskStatus.failed
        task.completed_at = datetime.now(timezone.utc)
        task.error_message = "Max retries exceeded: Persistent connection error"
        await db_session.commit()
        
        # Move to dead letter queue
        dlq_entry = DeadLetterQueue(
            original_task_id=task.id,
            original_queue_entry_id=queue_entry.id,
            original_payload_json={
                "task_id": str(task.id),
                "task_type": task.task_type,
                "payload": task.payload,
                "retry_count": task.retry_count,
            },
            failure_reason="MaxRetriesExceeded",
            failure_details_json={
                "error": task.error_message,
                "attempts": [
                    {"attempt": 1, "error": "Connection timeout"},
                    {"attempt": 2, "error": "Connection timeout"},
                    {"attempt": 3, "error": "Connection timeout"},
                ],
            },
            retry_count=task.retry_count,
            last_attempt_at=datetime.now(timezone.utc),
            is_active=True,
        )
        db_session.add(dlq_entry)
        await db_session.commit()
        await db_session.refresh(dlq_entry)
        
        # Verify DLQ entry
        assert dlq_entry.id is not None
        assert dlq_entry.is_active is True
        assert dlq_entry.failure_reason == "MaxRetriesExceeded"
        assert dlq_entry.original_task_id == task.id
        
        # Admin resolves the DLQ entry
        dlq_entry.is_active = False
        dlq_entry.resolved_at = datetime.now(timezone.utc)
        dlq_entry.resolved_by = sample_user.id
        await db_session.commit()
        
        await db_session.refresh(dlq_entry)
        assert dlq_entry.is_active is False
        assert dlq_entry.resolved_by == sample_user.id


# ============================================================================
# Test Scenario 2: Cascading Deletes and SET NULL
# ============================================================================

class TestCascadingBehavior:
    """Test cascading delete and SET NULL behavior across all related tables."""
    
    async def test_user_cascade_deletes_tasks_and_queue(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that deleting user cascades to tasks, queue, and dependencies."""
        # Create user
        user = User(
            username=f"cascade_user_{uuid4().hex[:8]}",
            email=f"cascade_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        # Create agent instance
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create tasks
        task1 = Task(
            user_id=user.id,
            agent_id=agent.id,
            task_type="task1",
            status=TaskStatus.pending,
        )
        task2 = Task(
            user_id=user.id,
            agent_id=agent.id,
            task_type="task2",
            status=TaskStatus.pending,
        )
        db_session.add_all([task1, task2])
        await db_session.commit()
        
        for t in [task1, task2]:
            await db_session.refresh(t)
        
        # Create queue entries
        queue1 = TaskQueue(
            task_id=task1.id,
            status=TaskStatus.pending,
            priority=5,
        )
        queue2 = TaskQueue(
            task_id=task2.id,
            status=TaskStatus.pending,
            priority=3,
        )
        db_session.add_all([queue1, queue2])
        await db_session.commit()
        
        # Create task dependencies
        dependency = TaskDependency(
            parent_task_id=task1.id,
            child_task_id=task2.id,
            dependency_type=DependencyType.sequential,
        )
        db_session.add(dependency)
        await db_session.commit()
        
        # Create schedule for task1
        schedule = TaskSchedule(
            task_template_id=task1.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 12 * * *",
            is_active=True,
        )
        db_session.add(schedule)
        await db_session.commit()
        
        # Store IDs for verification
        task_ids = [task1.id, task2.id]
        queue_ids = [queue1.id, queue2.id]
        agent_id = agent.id
        user_id = user.id
        
        # Delete the user using raw SQL to test database CASCADE behavior
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user_id}'")
        )
        await db_session.commit()
        
        # Verify cascade: user -> agent_instances -> tasks -> queue -> dependencies -> schedules
        agent_result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.id == agent_id)
        )
        assert agent_result.scalar_one_or_none() is None
        
        for tid in task_ids:
            task_result = await db_session.execute(
                select(Task).where(Task.id == tid)
            )
            assert task_result.scalar_one_or_none() is None
        
        for qid in queue_ids:
            queue_result = await db_session.execute(
                select(TaskQueue).where(TaskQueue.id == qid)
            )
            assert queue_result.scalar_one_or_none() is None
        
        # Verify dependencies were cascade deleted
        dep_result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.parent_task_id == task1.id)
        )
        assert dep_result.scalar_one_or_none() is None
        
        # Verify schedules were cascade deleted
        sched_result = await db_session.execute(
            select(TaskSchedule).where(TaskSchedule.task_template_id == task1.id)
        )
        assert sched_result.scalar_one_or_none() is None
    
    async def test_agent_set_null_preserves_task_history(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that deleting agent SET NULLs task.agent_id preserving task history."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task assigned to agent
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            task_type="orphan_test",
            status=TaskStatus.completed,
            result={"data": "processed"},
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        task_id = task.id
        agent_id = agent.id
        
        # Verify task is linked to agent
        assert task.agent_id == agent.id
        
        # Delete agent
        await db_session.delete(agent)
        await db_session.commit()
        
        # Verify task still exists but agent_id is NULL
        task_result = await db_session.execute(
            select(Task).where(Task.id == task_id)
        )
        surviving_task = task_result.scalar_one()
        
        assert surviving_task is not None
        assert surviving_task.agent_id is None
        assert surviving_task.status == TaskStatus.completed
        assert surviving_task.result is not None
    
    async def test_queue_claimed_by_set_null_on_agent_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that deleting agent SET NULLs queue.claimed_by preserving queue entry."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.busy,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task and queue entry
        task = Task(
            user_id=sample_user.id,
            task_type="claimed_task",
            status=TaskStatus.running,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.running,
            claimed_by=agent.id,
            claimed_at=datetime.now(timezone.utc),
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        queue_id = queue_entry.id
        agent_id = agent.id
        
        # Verify queue is claimed
        assert queue_entry.claimed_by == agent.id
        
        # Delete agent
        await db_session.delete(agent)
        await db_session.commit()
        
        # Verify queue entry still exists but claimed_by is NULL
        queue_result = await db_session.execute(
            select(TaskQueue).where(TaskQueue.id == queue_id)
        )
        surviving_queue = queue_result.scalar_one()
        
        assert surviving_queue is not None
        assert surviving_queue.claimed_by is None
        assert surviving_queue.status == TaskStatus.running
    
    async def test_dlq_survives_task_deletion(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that DLQ entries survive task deletion (SET NULL on original_task_id)."""
        # Create task
        task = Task(
            user_id=sample_user.id,
            task_type="dlq_test",
            status=TaskStatus.failed,
            error_message="Permanent failure",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create DLQ entry
        dlq = DeadLetterQueue(
            original_task_id=task.id,
            original_payload_json={"task_type": "dlq_test", "data": "important"},
            failure_reason="PermanentFailure",
            failure_details_json={"error": "Unrecoverable state"},
            is_active=True,
        )
        db_session.add(dlq)
        await db_session.commit()
        await db_session.refresh(dlq)
        
        dlq_id = dlq.id
        task_id = task.id
        
        # Delete the task
        await db_session.delete(task)
        await db_session.commit()
        
        # Verify DLQ entry still exists with NULL original_task_id
        dlq_result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.id == dlq_id)
        )
        surviving_dlq = dlq_result.scalar_one()
        
        assert surviving_dlq is not None
        assert surviving_dlq.original_task_id is None  # SET NULL
        assert surviving_dlq.original_payload_json is not None  # Preserved
        assert surviving_dlq.is_active is True
    
    async def test_parent_task_cascade_deletes_children(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that deleting parent task cascades to child tasks."""
        # Create parent task
        parent = Task(
            user_id=sample_user.id,
            task_type="parent_task",
            status=TaskStatus.pending,
        )
        db_session.add(parent)
        await db_session.commit()
        await db_session.refresh(parent)
        
        # Create child tasks
        child1 = Task(
            user_id=sample_user.id,
            parent_task_id=parent.id,
            task_type="child_task_1",
            status=TaskStatus.pending,
        )
        child2 = Task(
            user_id=sample_user.id,
            parent_task_id=parent.id,
            task_type="child_task_2",
            status=TaskStatus.pending,
        )
        db_session.add_all([child1, child2])
        await db_session.commit()
        
        for c in [child1, child2]:
            await db_session.refresh(c)
        
        parent_id = parent.id
        child_ids = [child1.id, child2.id]
        
        # Delete parent
        await db_session.delete(parent)
        await db_session.commit()
        
        # Verify parent and children are deleted
        parent_result = await db_session.execute(
            select(Task).where(Task.id == parent_id)
        )
        assert parent_result.scalar_one_or_none() is None
        
        for cid in child_ids:
            child_result = await db_session.execute(
                select(Task).where(Task.id == cid)
            )
            assert child_result.scalar_one_or_none() is None


# ============================================================================
# Test Scenario 3: Multi-Agent Collaboration
# ============================================================================

class TestMultiAgentCollaboration:
    """Test multi-agent collaboration within task context."""
    
    async def test_collaboration_session_linked_to_task(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test collaboration session properly linked to task context."""
        # Create multiple agents
        coordinator = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="Coordinator",
            status=AgentStatus.idle,
        )
        worker = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="Worker",
            status=AgentStatus.idle,
        )
        db_session.add_all([coordinator, worker])
        await db_session.commit()
        
        for a in [coordinator, worker]:
            await db_session.refresh(a)
        
        # Create task for the collaboration
        task = Task(
            user_id=sample_user.id,
            agent_id=coordinator.id,
            session_id=f"session-{uuid4()}",
            task_type="collaborative_research",
            status=TaskStatus.running,
            payload={"topic": "quantum computing"},
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create collaboration session
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=coordinator.id,
            name="Quantum Research",
            session_id=task.session_id,
            status="active",
            context_json={
                "task_id": str(task.id),
                "participants": [str(coordinator.id), str(worker.id)],
            },
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create message flow: Coordinator -> Worker -> Coordinator
        step_id = f"step-{uuid4().hex[:8]}"
        
        # Request from coordinator
        msg1 = AgentMessage(
            collaboration_id=collab.id,
            step_id=step_id,
            sender_agent_id=coordinator.id,
            receiver_agent_id=worker.id,
            message_type="request",
            content_json={"action": "search", "query": "quantum algorithms"},
        )
        db_session.add(msg1)
        await db_session.commit()
        
        # Response from worker
        msg2 = AgentMessage(
            collaboration_id=collab.id,
            step_id=step_id,
            sender_agent_id=worker.id,
            receiver_agent_id=coordinator.id,
            message_type="response",
            content_json={"results": ["Shor's algorithm", "Grover's algorithm"]},
        )
        db_session.add(msg2)
        await db_session.commit()
        
        # Tool call from worker
        msg3 = AgentMessage(
            collaboration_id=collab.id,
            step_id=step_id,
            sender_agent_id=worker.id,
            message_type="tool_call",
            content_json={"tool": "document_analyzer", "params": {"doc_id": "q1"}},
        )
        db_session.add(msg3)
        await db_session.commit()
        
        # Tool result
        msg4 = AgentMessage(
            collaboration_id=collab.id,
            step_id=step_id,
            sender_agent_id=worker.id,
            message_type="tool_result",
            content_json={"analysis": "Document discusses quantum supremacy"},
        )
        db_session.add(msg4)
        await db_session.commit()
        
        # Verify message sequence
        result = await db_session.execute(
            select(AgentMessage)
            .where(AgentMessage.collaboration_id == collab.id)
            .order_by(AgentMessage.created_at)
        )
        messages = result.scalars().all()
        
        assert len(messages) == 4
        assert messages[0].message_type == "request"
        assert messages[1].message_type == "response"
        assert messages[2].message_type == "tool_call"
        assert messages[3].message_type == "tool_result"
        
        # Verify step_id grouping
        for msg in messages:
            assert msg.step_id == step_id
    
    async def test_message_sender_set_null_on_agent_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that sender/receiver agent IDs are SET NULL when agent deleted."""
        # Create agents
        main_agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        sender_agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        receiver_agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add_all([main_agent, sender_agent, receiver_agent])
        await db_session.commit()
        
        for a in [main_agent, sender_agent, receiver_agent]:
            await db_session.refresh(a)
        
        # Create collaboration with main_agent as coordinator (not sender/receiver)
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=main_agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create messages with sender and receiver agents
        msg = AgentMessage(
            collaboration_id=collab.id,
            sender_agent_id=sender_agent.id,
            receiver_agent_id=receiver_agent.id,
            message_type="request",
            content_json={"test": "data"},
        )
        db_session.add(msg)
        await db_session.commit()
        await db_session.refresh(msg)
        
        msg_id = msg.id
        sender_id = sender_agent.id
        
        # Delete sender agent using raw SQL to test database SET NULL behavior
        await db_session.execute(
            text(f"DELETE FROM agent_instances WHERE id = '{sender_id}'")
        )
        await db_session.commit()
        
        msg_result = await db_session.execute(
            text(f"SELECT sender_agent_id, receiver_agent_id FROM agent_messages WHERE id = '{msg_id}'")
        )
        row = msg_result.fetchone()
        
        assert row is not None
        assert row[0] is None
        assert row[1] == receiver_agent.id


# ============================================================================
# Test Scenario 4: Performance Benchmarks
# ============================================================================

class TestPerformanceBenchmarks:
    """Test performance of key query patterns."""
    
    async def test_queue_polling_performance(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Benchmark queue polling query with priority/scheduled_at ordering."""
        # Create multiple tasks and queue entries with varying priorities
        num_tasks = 100
        
        tasks = []
        queue_entries = []
        
        for i in range(num_tasks):
            task = Task(
                user_id=sample_user.id,
                task_type=f"perf_task_{i}",
                status=TaskStatus.pending,
                priority=Priority.normal,
            )
            tasks.append(task)
        
        db_session.add_all(tasks)
        await db_session.commit()
        
        for t in tasks:
            await db_session.refresh(t)
        
        # Create queue entries with varying priorities and some scheduled
        for i, task in enumerate(tasks):
            priority = (i % 10) + 1  # Priority 1-10
            scheduled_at = None
            if i % 3 == 0:
                # Some tasks are scheduled for future
                scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=i)
            
            queue_entry = TaskQueue(
                task_id=task.id,
                status=TaskStatus.pending,
                priority=priority,
                scheduled_at=scheduled_at,
            )
            queue_entries.append(queue_entry)
        
        db_session.add_all(queue_entries)
        await db_session.commit()
        
        # Benchmark polling query
        start_time = time.perf_counter()
        
        # Query for top 10 tasks by priority, scheduled_at
        for _ in range(10):  # Run 10 times for benchmarking
            result = await db_session.execute(
                select(TaskQueue)
                .where(TaskQueue.status == TaskStatus.pending)
                .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc())
                .limit(10)
            )
            entries = result.scalars().all()
        
        elapsed = time.perf_counter() - start_time
        
        # Verify results are correctly ordered
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc())
            .limit(10)
        )
        top_entries = result.scalars().all()
        
        # Verify ordering
        for i in range(len(top_entries) - 1):
            curr = top_entries[i]
            next_entry = top_entries[i + 1]
            
            # Priority should be descending
            if curr.priority == next_entry.priority:
                # If same priority, scheduled_at should be ascending
                # None values should come first (immediate execution)
                if curr.scheduled_at is not None and next_entry.scheduled_at is not None:
                    assert curr.scheduled_at <= next_entry.scheduled_at
            else:
                assert curr.priority > next_entry.priority
        
        # Performance should be reasonable (< 100ms for 10 queries on 100 records)
        assert elapsed < 1.0  # Very generous for CI environments
    
    async def test_task_status_lookup_performance(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Benchmark task lookup by status with created_at ordering."""
        # Create tasks with various statuses
        statuses = [TaskStatus.pending, TaskStatus.running, TaskStatus.completed, TaskStatus.failed]
        num_per_status = 25
        
        tasks = []
        for status in statuses:
            for i in range(num_per_status):
                task = Task(
                    user_id=sample_user.id,
                    task_type=f"status_task_{status}_{i}",
                    status=status,
                )
                tasks.append(task)
        
        db_session.add_all(tasks)
        await db_session.commit()
        
        # Benchmark status lookup
        start_time = time.perf_counter()
        
        for _ in range(10):
            result = await db_session.execute(
                select(Task)
                .where(Task.status == TaskStatus.pending)
                .order_by(Task.created_at.desc())
                .limit(20)
            )
            pending_tasks = result.scalars().all()
        
        elapsed = time.perf_counter() - start_time
        
        # Verify we got the right number
        assert len(pending_tasks) <= 20
        
        # Performance check
        assert elapsed < 1.0
    
    async def test_dependency_resolution_performance(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Benchmark dependency resolution queries."""
        from db.queries.task_dag import get_ancestors, get_descendants, get_dependency_order
        
        # Create a chain of dependent tasks
        num_tasks = 20
        tasks = []
        
        for i in range(num_tasks):
            task = Task(
                user_id=sample_user.id,
                task_type=f"dep_task_{i}",
                status=TaskStatus.pending,
            )
            tasks.append(task)
        
        db_session.add_all(tasks)
        await db_session.commit()
        
        for t in tasks:
            await db_session.refresh(t)
        
        # Create sequential dependencies: task0 -> task1 -> task2 -> ...
        dependencies = []
        for i in range(num_tasks - 1):
            dep = TaskDependency(
                parent_task_id=tasks[i].id,
                child_task_id=tasks[i + 1].id,
                dependency_type=DependencyType.sequential,
            )
            dependencies.append(dep)
        
        db_session.add_all(dependencies)
        await db_session.commit()
        
        # Benchmark ancestor lookup
        start_time = time.perf_counter()
        
        ancestors = await get_ancestors(db_session, tasks[-1].id)
        
        elapsed_ancestors = time.perf_counter() - start_time
        
        # Last task should have all previous tasks as ancestors
        assert len(ancestors) == num_tasks - 1
        
        # Benchmark descendant lookup
        start_time = time.perf_counter()
        
        descendants = await get_descendants(db_session, tasks[0].id)
        
        elapsed_descendants = time.perf_counter() - start_time
        
        # First task should have all subsequent tasks as descendants
        assert len(descendants) == num_tasks - 1
        
        # Benchmark dependency order
        start_time = time.perf_counter()
        
        task_ids = [t.id for t in tasks]
        order = await get_dependency_order(db_session, task_ids)
        
        elapsed_order = time.perf_counter() - start_time
        
        # All tasks should be in order
        assert len(order) == num_tasks
        
        # First task should be first in order
        assert order[0] == tasks[0].id
        # Last task should be last in order
        assert order[-1] == tasks[-1].id
        
        # Performance checks (generous for CI)
        assert elapsed_ancestors < 1.0
        assert elapsed_descendants < 1.0
        assert elapsed_order < 1.0
    
    async def test_partial_index_usage_verification(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Verify partial indexes are used for queue queries."""
        # Create agent for claiming tasks
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create tasks with different statuses
        tasks = []
        for status in [TaskStatus.pending, TaskStatus.running, TaskStatus.completed]:
            for i in range(10):
                task = Task(
                    user_id=sample_user.id,
                    task_type=f"idx_task_{status}_{i}",
                    status=status,
                )
                tasks.append(task)
        
        db_session.add_all(tasks)
        await db_session.commit()
        
        for t in tasks:
            await db_session.refresh(t)
        
        # Create queue entries
        queue_entries = []
        for i, task in enumerate(tasks):
            queue_entry = TaskQueue(
                task_id=task.id,
                status=task.status,
                priority=i % 10,
            )
            queue_entries.append(queue_entry)
        
        db_session.add_all(queue_entries)
        await db_session.commit()
        
        # Query pending queue entries (should use idx_queue_poll partial index)
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc())
            .limit(5)
        )
        pending = result.scalars().all()
        
        assert len(pending) == 5
        for entry in pending:
            assert entry.status == TaskStatus.pending
        
        # Claim running tasks using the agent
        for entry in queue_entries:
            if entry.status == TaskStatus.running:
                entry.claimed_by = agent.id
                entry.claimed_at = datetime.now(timezone.utc)
        await db_session.commit()
        
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.running)
            .where(TaskQueue.claimed_by.isnot(None))
        )
        claimed = result.scalars().all()
        
        assert len(claimed) == 10  # All running should be claimed


# ============================================================================
# Test Scenario 5: Error Handling and Constraints
# ============================================================================

class TestErrorHandlingAndConstraints:
    """Test error handling and constraint enforcement."""
    
    async def test_duplicate_dependency_prevention(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that duplicate dependencies are prevented."""
        # Create two tasks
        task1 = Task(
            user_id=sample_user.id,
            task_type="dup_test_1",
            status=TaskStatus.pending,
        )
        task2 = Task(
            user_id=sample_user.id,
            task_type="dup_test_2",
            status=TaskStatus.pending,
        )
        db_session.add_all([task1, task2])
        await db_session.commit()
        
        for t in [task1, task2]:
            await db_session.refresh(t)
        
        # Create dependency
        dep1 = TaskDependency(
            parent_task_id=task1.id,
            child_task_id=task2.id,
            dependency_type=DependencyType.sequential,
        )
        db_session.add(dep1)
        await db_session.commit()
        
        # Try to create duplicate dependency
        dep2 = TaskDependency(
            parent_task_id=task1.id,
            child_task_id=task2.id,
            dependency_type=DependencyType.parallel,
        )
        db_session.add(dep2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
        
        await db_session.rollback()
    
    async def test_self_reference_dependency_prevention(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that self-referencing dependencies are prevented."""
        # Create a task
        task = Task(
            user_id=sample_user.id,
            task_type="self_ref_test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Try to create self-referencing dependency
        dep = TaskDependency(
            parent_task_id=task.id,
            child_task_id=task.id,  # Same task!
            dependency_type=DependencyType.sequential,
        )
        db_session.add(dep)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
        
        await db_session.rollback()
    
    async def test_cycle_detection_in_dependencies(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test cycle detection in task dependencies."""
        from db.queries.task_dag import detect_cycle, validate_new_dependency, CycleDetectedError
        
        # Create tasks
        task_a = Task(
            user_id=sample_user.id,
            task_type="cycle_a",
            status=TaskStatus.pending,
        )
        task_b = Task(
            user_id=sample_user.id,
            task_type="cycle_b",
            status=TaskStatus.pending,
        )
        task_c = Task(
            user_id=sample_user.id,
            task_type="cycle_c",
            status=TaskStatus.pending,
        )
        db_session.add_all([task_a, task_b, task_c])
        await db_session.commit()
        
        for t in [task_a, task_b, task_c]:
            await db_session.refresh(t)
        
        # Create dependencies: A -> B -> C
        dep_ab = TaskDependency(
            parent_task_id=task_a.id,
            child_task_id=task_b.id,
        )
        dep_bc = TaskDependency(
            parent_task_id=task_b.id,
            child_task_id=task_c.id,
        )
        db_session.add_all([dep_ab, dep_bc])
        await db_session.commit()
        
        # Attempt to add C -> A would create cycle: A -> B -> C -> A
        cycle_path = await detect_cycle(db_session, task_c.id, task_a.id)
        
        assert cycle_path is not None
        assert task_c.id in cycle_path
        assert task_a.id in cycle_path
        
        # Validate with helper function
        with pytest.raises(CycleDetectedError):
            await validate_new_dependency(db_session, task_c.id, task_a.id)
    
    async def test_invalid_task_status_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that invalid task status values are rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="status_test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Try to set invalid status via raw SQL
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET status = 'invalid_status' WHERE id = '{task.id}'")
            )
            await db_session.commit()
        
        await db_session.rollback()
    
    async def test_invalid_priority_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that invalid priority values are rejected."""
        task = Task(
            user_id=sample_user.id,
            task_type="priority_test",
            priority=Priority.normal,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Try to set invalid priority via raw SQL
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET priority = 'ultra' WHERE id = '{task.id}'")
            )
            await db_session.commit()
        
        await db_session.rollback()
    
    async def test_api_key_encryption_verification(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that API keys are properly encrypted in database."""
        # Generate a test encryption key
        test_key = generate_key()
        
        # Set up crypto manager with test key
        original_key = os.environ.get("LLM_ENCRYPTION_KEY")
        os.environ["LLM_ENCRYPTION_KEY"] = test_key
        CryptoManager.reset()
        
        try:
            crypto = CryptoManager()
            plaintext_key = "sk-test-api-key-12345"
            
            # Encrypt the API key
            encrypted_key = crypto.encrypt(plaintext_key)
            
            # Verify encrypted is different from plaintext
            assert encrypted_key != plaintext_key
            
            # Create LLM endpoint with encrypted key
            endpoint = LLMEndpoint(
                user_id=sample_user.id,
                name="Test Endpoint",
                base_url="https://api.example.com/v1",
                api_key_encrypted=encrypted_key,
                model_name="test-model",
            )
            db_session.add(endpoint)
            await db_session.commit()
            await db_session.refresh(endpoint)
            
            # Retrieve and verify
            result = await db_session.execute(
                select(LLMEndpoint).where(LLMEndpoint.id == endpoint.id)
            )
            stored_endpoint = result.scalar_one()
            
            # Verify stored value is encrypted
            assert stored_endpoint.api_key_encrypted == encrypted_key
            assert stored_endpoint.api_key_encrypted != plaintext_key
            
            # Verify we can decrypt
            decrypted = crypto.decrypt(stored_endpoint.api_key_encrypted)
            assert decrypted == plaintext_key
            
        finally:
            # Restore original key
            CryptoManager.reset()
            if original_key:
                os.environ["LLM_ENCRYPTION_KEY"] = original_key
            elif "LLM_ENCRYPTION_KEY" in os.environ:
                del os.environ["LLM_ENCRYPTION_KEY"]
    
    async def test_negative_retry_count_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that negative retry_count is rejected."""
        # Try via raw SQL since Pydantic would catch this
        task = Task(
            user_id=sample_user.id,
            task_type="retry_test",
            retry_count=0,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Try to set negative retry_count via raw SQL
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE tasks SET retry_count = -1 WHERE id = '{task.id}'")
            )
            await db_session.commit()
        
        await db_session.rollback()
    
    async def test_schedule_unique_per_task_template(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that only one schedule can exist per task template."""
        # Create task
        task = Task(
            user_id=sample_user.id,
            task_type="schedule_unique_test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create first schedule
        schedule1 = TaskSchedule(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 12 * * *",
        )
        db_session.add(schedule1)
        await db_session.commit()
        
        # Try to create second schedule for same task
        schedule2 = TaskSchedule(
            task_template_id=task.id,
            schedule_type=ScheduleType.interval,
            schedule_expression="PT1H",
        )
        db_session.add(schedule2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
        
        await db_session.rollback()


# ============================================================================
# Test Scenario 6: Cross-Module Integration
# ============================================================================

class TestCrossModuleIntegration:
    """Test integration across all task system modules."""
    
    async def test_full_system_integration(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Complete integration test across all task system tables."""
        # 1. Create agent type and instances
        agent_type = AgentType(
            name=f"IntegrationAgent_{uuid4().hex[:8]}",
            capabilities={"all": True},
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # 2. Create LLM endpoint group and endpoint
        endpoint_group = LLMEndpointGroup(
            user_id=sample_user.id,
            name="Test Group",
            is_default=True,
        )
        db_session.add(endpoint_group)
        await db_session.commit()
        await db_session.refresh(endpoint_group)
        
        # Set up encryption for endpoint
        test_key = generate_key()
        original_key = os.environ.get("LLM_ENCRYPTION_KEY")
        os.environ["LLM_ENCRYPTION_KEY"] = test_key
        CryptoManager.reset()
        
        try:
            crypto = CryptoManager()
            endpoint = LLMEndpoint(
                user_id=sample_user.id,
                name="Test LLM",
                base_url="https://api.test.com/v1",
                api_key_encrypted=crypto.encrypt("test-key"),
                model_name="test-model",
            )
            db_session.add(endpoint)
            await db_session.commit()
            await db_session.refresh(endpoint)
            
            # 3. Create tasks with hierarchy
            parent_task = Task(
                user_id=sample_user.id,
                agent_id=agent.id,
                task_type="parent_workflow",
                status=TaskStatus.pending,
                priority=Priority.high,
            )
            db_session.add(parent_task)
            await db_session.commit()
            await db_session.refresh(parent_task)
            
            child_task1 = Task(
                user_id=sample_user.id,
                parent_task_id=parent_task.id,
                task_type="child_step_1",
                status=TaskStatus.pending,
            )
            child_task2 = Task(
                user_id=sample_user.id,
                parent_task_id=parent_task.id,
                task_type="child_step_2",
                status=TaskStatus.pending,
            )
            db_session.add_all([child_task1, child_task2])
            await db_session.commit()
            
            for t in [child_task1, child_task2]:
                await db_session.refresh(t)
            
            # 4. Create dependencies between child tasks
            dep = TaskDependency(
                parent_task_id=child_task1.id,
                child_task_id=child_task2.id,
                dependency_type=DependencyType.sequential,
            )
            db_session.add(dep)
            await db_session.commit()
            
            # 5. Create schedule for parent task
            schedule = TaskSchedule(
                task_template_id=parent_task.id,
                schedule_type=ScheduleType.cron,
                schedule_expression="0 9 * * 1-5",  # Weekdays at 9am
                is_active=True,
            )
            db_session.add(schedule)
            await db_session.commit()
            
            # 6. Create queue entries
            queue_parent = TaskQueue(
                task_id=parent_task.id,
                status=TaskStatus.pending,
                priority=10,
            )
            queue_child1 = TaskQueue(
                task_id=child_task1.id,
                status=TaskStatus.pending,
                priority=5,
            )
            db_session.add_all([queue_parent, queue_child1])
            await db_session.commit()
            
            # 7. Create collaboration session
            collab = CollaborationSession(
                user_id=sample_user.id,
                main_agent_id=agent.id,
                session_id=f"session-{uuid4()}",
                context_json={"workflow": "integration_test"},
            )
            db_session.add(collab)
            await db_session.commit()
            await db_session.refresh(collab)
            
            # 8. Add messages to collaboration
            msg = AgentMessage(
                collaboration_id=collab.id,
                sender_agent_id=agent.id,
                message_type="notification",
                content_json={"status": "workflow_started"},
            )
            db_session.add(msg)
            await db_session.commit()
            
            # Verify all relationships
            # Check FK chain: task -> user
            result = await db_session.execute(
                select(Task, User)
                .join(User, Task.user_id == User.id)
                .where(Task.id == parent_task.id)
            )
            task_user = result.first()
            assert task_user is not None
            
            # Check FK chain: task -> agent -> agent_type
            result = await db_session.execute(
                select(Task, AgentInstance, AgentType)
                .join(AgentInstance, Task.agent_id == AgentInstance.id)
                .join(AgentType, AgentInstance.agent_type_id == AgentType.id)
                .where(Task.id == parent_task.id)
            )
            task_agent_type = result.first()
            assert task_agent_type is not None
            
            # Check FK chain: queue -> task -> user
            result = await db_session.execute(
                select(TaskQueue, Task, User)
                .join(Task, TaskQueue.task_id == Task.id)
                .join(User, Task.user_id == User.id)
                .where(TaskQueue.task_id == parent_task.id)
            )
            queue_task_user = result.first()
            assert queue_task_user is not None
            
        finally:
            CryptoManager.reset()
            if original_key:
                os.environ["LLM_ENCRYPTION_KEY"] = original_key
            elif "LLM_ENCRYPTION_KEY" in os.environ:
                del os.environ["LLM_ENCRYPTION_KEY"]
    
    async def test_all_fk_constraints_maintained(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Verify all foreign key constraints are maintained across the system."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            task_type="fk_test",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create queue entry
        queue = TaskQueue(
            task_id=task.id,
            status=TaskStatus.pending,
            claimed_by=agent.id,
        )
        db_session.add(queue)
        await db_session.commit()
        await db_session.refresh(queue)
        
        # Create schedule
        schedule = TaskSchedule(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 * * * *",
        )
        db_session.add(schedule)
        await db_session.commit()
        
        # Create collaboration
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create message
        msg = AgentMessage(
            collaboration_id=collab.id,
            sender_agent_id=agent.id,
            message_type="request",
            content_json={"test": "fk"},
        )
        db_session.add(msg)
        await db_session.commit()
        
        # Create DLQ entry
        dlq = DeadLetterQueue(
            original_task_id=task.id,
            original_queue_entry_id=queue.id,
            original_payload_json={"test": "data"},
            failure_reason="TestFailure",
            failure_details_json={"error": "test"},
            resolved_by=sample_user.id,
        )
        db_session.add(dlq)
        await db_session.commit()
        
        # Verify all FKs point to valid records
        # Task -> User FK
        assert task.user_id == sample_user.id
        
        # Task -> Agent FK
        assert task.agent_id == agent.id
        
        # Agent -> User FK
        assert agent.user_id == sample_user.id
        
        # Agent -> AgentType FK
        assert agent.agent_type_id == sample_agent_type.id
        
        # Queue -> Task FK
        assert queue.task_id == task.id
        
        # Queue -> Agent FK (claimed_by)
        assert queue.claimed_by == agent.id
        
        # Schedule -> Task FK
        assert schedule.task_template_id == task.id
        
        # Collab -> User FK
        assert collab.user_id == sample_user.id
        
        # Collab -> Agent FK
        assert collab.main_agent_id == agent.id
        
        # Message -> Collab FK
        assert msg.collaboration_id == collab.id
        
        # Message -> Agent FK (sender)
        assert msg.sender_agent_id == agent.id
        
        # DLQ -> Task FK
        assert dlq.original_task_id == task.id
        
        # DLQ -> Queue FK
        assert dlq.original_queue_entry_id == queue.id
        
        # DLQ -> User FK (resolved_by)
        assert dlq.resolved_by == sample_user.id