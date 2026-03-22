# pyright: reportMissingImports=false
"""
Comprehensive end-to-end integration tests for the agent-server system.

This module tests the complete flow across all core system modules:
- users
- agent_types, agent_instances
- agent_capabilities
- collaboration_sessions, agent_messages
- tasks, task_queue, task_dependencies, task_schedules
- dead_letter_queue
- tools, tool_versions, tool_calls
- token_usage
- audit_log (audit schema)

Test scenarios:
1. Complete user → agent → task → tool call → token usage → audit log flow
2. Multi-agent collaboration with tasks
3. Task queue processing with LangGraph checkpoint integration
4. Hierarchical task decomposition and dependencies
5. Cross-module data integrity and relationship validation
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.schema.agents import AgentType, AgentInstance
from db.schema.agent_capabilities import AgentCapability
from db.schema.collaboration import (
    CollaborationSession,
    AgentMessage,
    CollaborationStatus,
    MessageRedactionLevel,
    MessageType,
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
    """Create a test database session with all system tables.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation with full schema setup.
    """
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
        # 1. Create audit schema first
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        
        # 2. Create users table (root dependency)
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
        
        # 3. Create agent_types table
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
        
        # 4. Create agent_instances table
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
        
        # 5. Create agent_capabilities table
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
        
        # 6. Create collaboration_sessions table
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
        
        # 7. Create agent_messages table
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
        
        # 8. Create tasks table
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
        
        # 9. Create task_dependencies table
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
        
        # 10. Create task_schedules table
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
        
        # 11. Create task_queue table
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
        
        # 12. Create tools table
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
        
        # 13. Create tool_versions table
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
        
        # 14. Create tool_calls table
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
        
        # 15. Create token_usage table
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
        
        # 16. Create dead_letter_queue table
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
        
        # 17. Create audit.audit_log table
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
        
        # Create all indexes
        await _create_indexes(conn)
    
    async with async_session_maker() as session:
        yield session
        await session.rollback()
    
    # Clean up - drop tables after test (reverse dependency order)
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
    # Agent indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_types_name ON agent_types(name)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_instances_status ON agent_instances(status)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_instances_user ON agent_instances(user_id)"))
    
    # Capability indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_capabilities_type ON agent_capabilities(agent_type_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_capabilities_name ON agent_capabilities(capability_name)"))
    
    # Collaboration indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_user ON collaboration_sessions(user_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collab_status ON collaboration_sessions(status)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_collab ON agent_messages(collaboration_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_step ON agent_messages(step_id)"))
    
    # Task indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id)"))
    
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
    
    # Task dependencies indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_deps_parent ON task_dependencies(parent_task_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_deps_child ON task_dependencies(child_task_id)"))
    
    # Tools indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tools_is_active ON tools(is_active)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tool_versions_tool_id ON tool_versions(tool_id)"))
    
    # Tool calls indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool_id)"))
    
    # Token usage indexes
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_token_usage_user_created ON token_usage(user_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(session_id)"))
    
    # DLQ partial indexes
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_dlq_unresolved 
        ON dead_letter_queue(created_at DESC)
        WHERE is_active = true
    """))
    
    # Audit indexes
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_user_time 
        ON audit.audit_log(user_id, created_at DESC)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_resource 
        ON audit.audit_log(resource_type, resource_id)
    """))


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user for testing."""
    user = User(
        username=f"fulltest_{uuid4().hex[:8]}",
        email=f"fulltest_{uuid4().hex[:8]}@example.com",
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
        name=f"FullTestAgent_{uuid4().hex[:8]}",
        description="Agent type for full integration testing",
        capabilities={
            "web_search": True,
            "code_execution": True,
            "max_tokens": 8192,
        },
        default_config={
            "temperature": 0.7,
            "timeout_seconds": 300,
        },
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
        name=f"test_tool_{uuid4().hex[:8]}",
        description="A test tool for integration testing",
        is_active=True,
    )
    db_session.add(tool)
    await db_session.commit()
    await db_session.refresh(tool)
    return tool


# ============================================================================
# Test Scenario 1: Complete User → Agent → Task → Tool Call → Token Usage → Audit Log Flow
# ============================================================================

class TestCompleteSystemFlow:
    """Test the complete end-to-end flow across all system modules.
    
    This test validates the entire data flow:
    User -> Agent Type -> Agent Instance -> Task -> Queue -> 
    Tool Calls -> Token Usage -> Audit Log
    """
    
    async def test_full_system_workflow(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
        sample_tool: Tool,
    ):
        """Test complete workflow from user creation to audit logging."""
        # =====================================================================
        # Step 1: Create Agent Instance
        # =====================================================================
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="MainWorker-001",
            status=AgentStatus.idle,
            config={"custom_timeout": 600},
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.id is not None
        assert agent.status == AgentStatus.idle
        
        # =====================================================================
        # Step 2: Create Task
        # =====================================================================
        session_id = f"session-{uuid4()}"
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            session_id=session_id,
            task_type="research_analysis",
            status=TaskStatus.pending,
            priority=Priority.high,
            payload={
                "query": "Analyze quantum computing trends",
                "max_results": 10,
                "filters": {"year": 2026},
            },
            max_retries=3,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        assert task.id is not None
        assert task.status == TaskStatus.pending
        
        # =====================================================================
        # Step 3: Create Queue Entry and Process
        # =====================================================================
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.pending,
            priority=10,  # High priority
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Poll and claim the task
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc())
            .limit(1)
        )
        claimed = result.scalar_one()
        assert claimed.task_id == task.id
        
        # Update status to running
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = agent.id
        queue_entry.claimed_at = datetime.now(timezone.utc)
        queue_entry.started_at = datetime.now(timezone.utc)
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        agent.status = AgentStatus.busy
        await db_session.commit()
        
        # =====================================================================
        # Step 4: Create Tool Version
        # =====================================================================
        tool_version = ToolVersion(
            tool_id=sample_tool.id,
            version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array"},
                    "count": {"type": "integer"},
                },
            },
            is_default=True,
        )
        db_session.add(tool_version)
        await db_session.commit()
        await db_session.refresh(tool_version)
        
        # =====================================================================
        # Step 5: Create Tool Call
        # =====================================================================
        tool_call = ToolCall(
            task_id=task.id,
            tool_id=sample_tool.id,
            tool_version_id=tool_version.id,
            input={"query": "quantum computing trends", "limit": 10},
            status="pending",
        )
        db_session.add(tool_call)
        await db_session.commit()
        await db_session.refresh(tool_call)
        
        # Execute tool call
        tool_call.status = "running"
        await db_session.commit()
        
        # Complete tool call
        tool_call.status = "completed"
        tool_call.output = {
            "results": [
                {"title": "Quantum Advantage in 2026", "source": "nature.com"},
                {"title": "IBM's 1000+ Qubit Processor", "source": "arxiv.org"},
            ],
            "count": 2,
        }
        tool_call.duration_ms = 1250
        await db_session.commit()
        
        # =====================================================================
        # Step 6: Record Token Usage
        # =====================================================================
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=agent.id,
            session_id=session_id,
            model_name="gpt-4-turbo",
            input_tokens=1500,
            output_tokens=800,
            total_tokens=2300,
            estimated_cost_usd=Decimal("0.115000"),
        )
        db_session.add(token_usage)
        await db_session.commit()
        await db_session.refresh(token_usage)
        
        assert token_usage.id is not None
        assert token_usage.total_tokens == 2300
        
        # =====================================================================
        # Step 7: Complete Task
        # =====================================================================
        task.status = TaskStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        task.result = {
            "analysis": "Quantum computing is advancing rapidly...",
            "sources": 2,
            "confidence": 0.92,
        }
        queue_entry.status = TaskStatus.completed
        queue_entry.completed_at = datetime.now(timezone.utc)
        queue_entry.result_json = {"processed": True}
        agent.status = AgentStatus.idle
        await db_session.commit()
        
        # =====================================================================
        # Step 8: Create Audit Log Entry
        # =====================================================================
        audit_entry = await db_session.execute(
            text("""
                INSERT INTO audit.audit_log 
                (user_id, actor_type, actor_id, action, resource_type, resource_id, new_values)
                VALUES (:user_id, 'user', :actor_id, 'create', 'task', :resource_id, :new_values)
                RETURNING id
            """),
            {
                "user_id": str(sample_user.id),
                "actor_id": str(sample_user.id),
                "resource_id": str(task.id),
                "new_values": '{"task_type": "research_analysis", "status": "completed"}',
            },
        )
        audit_id = audit_entry.scalar()
        await db_session.commit()
        
        assert audit_id is not None
        
        # =====================================================================
        # Step 9: Verify Complete Chain
        # =====================================================================
        # Verify task with all relationships
        result = await db_session.execute(
            select(Task)
            .where(Task.id == task.id)
        )
        verified_task = result.scalar_one()
        assert verified_task.status == TaskStatus.completed
        assert verified_task.result is not None
        
        # Verify tool calls for task
        tc_result = await db_session.execute(
            select(ToolCall).where(ToolCall.task_id == task.id)
        )
        tool_calls = tc_result.scalars().all()
        assert len(tool_calls) == 1
        assert tool_calls[0].status == "completed"
        
        # Verify token usage
        tu_result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.session_id == session_id)
        )
        usages = tu_result.scalars().all()
        assert len(usages) == 1
        assert usages[0].total_tokens == 2300
        
        # Verify audit log
        audit_result = await db_session.execute(
            text("SELECT * FROM audit.audit_log WHERE resource_id = :resource_id"),
            {"resource_id": str(task.id)},
        )
        audit_row = audit_result.fetchone()
        assert audit_row is not None
    
    async def test_multiple_tool_calls_per_task(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that a task can have multiple tool calls tracked."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            task_type="multi_step_analysis",
            status=TaskStatus.running,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create multiple tools
        tools = []
        for name in ["web_search", "text_analyzer", "summarizer"]:
            tool = Tool(name=f"{name}_{uuid4().hex[:8]}", is_active=True)
            db_session.add(tool)
            tools.append(tool)
        await db_session.commit()
        for t in tools:
            await db_session.refresh(t)
        
        # Create tool calls for each tool
        tool_calls = []
        for i, tool in enumerate(tools):
            tc = ToolCall(
                task_id=task.id,
                tool_id=tool.id,
                input={"step": i + 1},
                status="completed",
                duration_ms=(i + 1) * 100,
                output={"result": f"step_{i + 1}_output"},
            )
            db_session.add(tc)
            tool_calls.append(tc)
        await db_session.commit()
        
        # Verify all tool calls
        result = await db_session.execute(
            select(ToolCall)
            .where(ToolCall.task_id == task.id)
            .order_by(ToolCall.created_at)
        )
        saved_calls = result.scalars().all()
        
        assert len(saved_calls) == 3
        for tc in saved_calls:
            assert tc.status == "completed"
            assert tc.duration_ms is not None
    
    async def test_token_usage_aggregation_per_session(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test token usage aggregation across multiple LLM calls in a session."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        session_id = f"session-{uuid4()}"
        
        # Create multiple token usage records
        usages = []
        for i in range(3):
            tu = TokenUsage(
                user_id=sample_user.id,
                agent_id=agent.id,
                session_id=session_id,
                model_name="gpt-4-turbo",
                input_tokens=500 * (i + 1),
                output_tokens=200 * (i + 1),
                total_tokens=700 * (i + 1),
                estimated_cost_usd=Decimal(f"{0.035 * (i + 1):.6f}"),
            )
            db_session.add(tu)
            usages.append(tu)
        await db_session.commit()
        
        # Aggregate token usage for session
        result = await db_session.execute(
            select(
                func.sum(TokenUsage.input_tokens).label("total_input"),
                func.sum(TokenUsage.output_tokens).label("total_output"),
                func.sum(TokenUsage.total_tokens).label("total_tokens"),
                func.sum(TokenUsage.estimated_cost_usd).label("total_cost"),
            ).where(TokenUsage.session_id == session_id)
        )
        row = result.one()
        
        assert row.total_input == 3000  # 500 + 1000 + 1500
        assert row.total_output == 1200  # 200 + 400 + 600
        assert row.total_tokens == 4200  # 700 + 1400 + 2100
        # Total cost: 0.035 + 0.07 + 0.105 = 0.21
        assert float(row.total_cost) == pytest.approx(0.21)


# ============================================================================
# Test Scenario 2: Multi-Agent Collaboration with Tasks
# ============================================================================

class TestMultiAgentCollaborationWithTasks:
    """Test multi-agent collaboration within task context."""
    
    async def test_coordinator_worker_pattern(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test coordinator-worker multi-agent pattern with tasks."""
        # Create agent types
        coordinator_type = AgentType(
            name=f"Coordinator_{uuid4().hex[:8]}",
            capabilities={"delegation": True, "aggregation": True},
            is_active=True,
        )
        worker_type = AgentType(
            name=f"Worker_{uuid4().hex[:8]}",
            capabilities={"execution": True, "reporting": True},
            is_active=True,
        )
        db_session.add_all([coordinator_type, worker_type])
        await db_session.commit()
        for t in [coordinator_type, worker_type]:
            await db_session.refresh(t)
        
        # Create agents
        coordinator = AgentInstance(
            agent_type_id=coordinator_type.id,
            user_id=sample_user.id,
            name="Coordinator-Main",
            status=AgentStatus.idle,
        )
        workers = [
            AgentInstance(
                agent_type_id=worker_type.id,
                user_id=sample_user.id,
                name=f"Worker-{i}",
                status=AgentStatus.idle,
            )
            for i in range(3)
        ]
        db_session.add_all([coordinator] + workers)
        await db_session.commit()
        for a in [coordinator] + workers:
            await db_session.refresh(a)
        
        # Create main task
        session_id = f"session-{uuid4()}"
        main_task = Task(
            user_id=sample_user.id,
            agent_id=coordinator.id,
            session_id=session_id,
            task_type="distributed_analysis",
            status=TaskStatus.running,
            payload={"workload": "heavy", "parallelism": 3},
        )
        db_session.add(main_task)
        await db_session.commit()
        await db_session.refresh(main_task)
        
        # Create collaboration session
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=coordinator.id,
            name="Distributed Task Execution",
            session_id=session_id,
            status=CollaborationStatus.active,
            context_json={
                "main_task_id": str(main_task.id),
                "workers": [str(w.id) for w in workers],
            },
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create child tasks for each worker
        child_tasks = []
        for i, worker in enumerate(workers):
            child = Task(
                user_id=sample_user.id,
                agent_id=worker.id,
                parent_task_id=main_task.id,
                task_type=f"subtask_{i}",
                status=TaskStatus.pending,
                payload={"chunk": i, "data": f"chunk_{i}_data"},
            )
            db_session.add(child)
            child_tasks.append(child)
        await db_session.commit()
        for t in child_tasks:
            await db_session.refresh(t)
        
        # Create task dependencies (children must complete before main)
        for child in child_tasks:
            dep = TaskDependency(
                parent_task_id=main_task.id,
                child_task_id=child.id,
                dependency_type=DependencyType.parallel,
            )
            db_session.add(dep)
        await db_session.commit()
        
        # Simulate message flow
        step_id = f"step-{uuid4().hex[:8]}"
        
        # Coordinator dispatches work
        for i, worker in enumerate(workers):
            msg = AgentMessage(
                collaboration_id=collab.id,
                step_id=step_id,
                sender_agent_id=coordinator.id,
                receiver_agent_id=worker.id,
                message_type=MessageType.request,
                content_json={"task": "process_chunk", "chunk_id": i},
            )
            db_session.add(msg)
        await db_session.commit()
        
        # Workers respond
        for worker in workers:
            msg = AgentMessage(
                collaboration_id=collab.id,
                step_id=step_id,
                sender_agent_id=worker.id,
                receiver_agent_id=coordinator.id,
                message_type=MessageType.response,
                content_json={"status": "processing"},
            )
            db_session.add(msg)
        await db_session.commit()
        
        # Complete child tasks
        for child in child_tasks:
            child.status = TaskStatus.completed
            child.result = {"processed": True}
        await db_session.commit()
        
        # Complete main task
        main_task.status = TaskStatus.completed
        main_task.result = {"all_chunks_processed": True}
        collab.status = CollaborationStatus.completed
        collab.ended_at = datetime.now(timezone.utc)
        coordinator.status = AgentStatus.idle
        await db_session.commit()
        
        # Verify structure
        # Check parent-child relationships
        children_result = await db_session.execute(
            select(Task).where(Task.parent_task_id == main_task.id)
        )
        saved_children = children_result.scalars().all()
        assert len(saved_children) == 3
        
        # Check messages
        msg_result = await db_session.execute(
            select(AgentMessage).where(AgentMessage.collaboration_id == collab.id)
        )
        messages = msg_result.scalars().all()
        assert len(messages) == 6  # 3 requests + 3 responses
        
        # Check dependencies
        dep_result = await db_session.execute(
            select(TaskDependency).where(TaskDependency.parent_task_id == main_task.id)
        )
        deps = dep_result.scalars().all()
        assert len(deps) == 3
    
    async def test_agent_capability_validation_in_collaboration(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that agents use capabilities defined in their type."""
        # Create agent type with specific capabilities
        agent_type = AgentType(
            name=f"CapableAgent_{uuid4().hex[:8]}",
            capabilities={"allowed_tools": ["search", "analyze"]},
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create capability definitions
        for cap_name in ["search", "analyze"]:
            cap = AgentCapability(
                agent_type_id=agent_type.id,
                capability_name=cap_name,
                input_schema={"type": "object"},
                is_active=True,
            )
            db_session.add(cap)
        await db_session.commit()
        
        # Create agent
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            task_type="capability_test",
            status=TaskStatus.running,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create collaboration
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Verify capabilities accessible
        cap_result = await db_session.execute(
            select(AgentCapability)
            .where(AgentCapability.agent_type_id == agent_type.id)
            .where(AgentCapability.is_active == True)
        )
        capabilities = cap_result.scalars().all()
        assert len(capabilities) == 2
        cap_names = {c.capability_name for c in capabilities}
        assert cap_names == {"search", "analyze"}


# ============================================================================
# Test Scenario 3: Task Queue Processing with Checkpoint
# ============================================================================

class TestTaskQueueWithCheckpoint:
    """Test task queue processing with LangGraph checkpoint integration."""
    
    async def test_queue_processing_with_session_checkpoint_link(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that queue processing maintains session_id for checkpoint linkage."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task with session_id (LangGraph thread_id)
        langgraph_thread_id = f"lg-thread-{uuid4()}"
        task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            session_id=langgraph_thread_id,
            task_type="checkpoint_enabled_task",
            status=TaskStatus.pending,
            payload={"checkpoint_enabled": True},
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create queue entry
        queue_entry = TaskQueue(
            task_id=task.id,
            status=TaskStatus.pending,
            priority=5,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        await db_session.refresh(queue_entry)
        
        # Poll queue
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc())
            .limit(1)
        )
        polled = result.scalar_one()
        assert polled.task_id == task.id
        
        # Claim and start processing
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = agent.id
        queue_entry.started_at = datetime.now(timezone.utc)
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        await db_session.commit()
        
        # Verify session_id linkage for checkpoint
        assert task.session_id == langgraph_thread_id
        
        # Complete processing
        task.status = TaskStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        task.result = {"checkpoint_restored": True, "processed": True}
        queue_entry.status = TaskStatus.completed
        queue_entry.completed_at = datetime.now(timezone.utc)
        await db_session.commit()
        
        # Verify task can be linked back to checkpoint thread
        result = await db_session.execute(
            select(Task).where(Task.session_id == langgraph_thread_id)
        )
        linked_task = result.scalar_one()
        assert linked_task.id == task.id
    
    async def test_scheduled_task_queue_processing(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test scheduled task creation with schedule and queue processing."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create template task
        template_task = Task(
            user_id=sample_user.id,
            task_type="scheduled_report",
            status=TaskStatus.pending,
            payload={"report_type": "daily_summary"},
        )
        db_session.add(template_task)
        await db_session.commit()
        await db_session.refresh(template_task)
        
        # Create schedule
        schedule = TaskSchedule(
            task_template_id=template_task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="0 9 * * *",  # Daily at 9 AM
            is_active=True,
            next_run_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db_session.add(schedule)
        await db_session.commit()
        await db_session.refresh(schedule)
        
        # Create actual execution task
        execution_task = Task(
            user_id=sample_user.id,
            agent_id=agent.id,
            task_type="scheduled_report_execution",
            status=TaskStatus.pending,
            scheduled_at=schedule.next_run_at,
        )
        db_session.add(execution_task)
        await db_session.commit()
        await db_session.refresh(execution_task)
        
        # Create queue entry for scheduled execution
        queue_entry = TaskQueue(
            task_id=execution_task.id,
            status=TaskStatus.pending,
            priority=3,
            scheduled_at=schedule.next_run_at,
        )
        db_session.add(queue_entry)
        await db_session.commit()
        
        # Verify schedule linkage
        sched_result = await db_session.execute(
            select(TaskSchedule).where(TaskSchedule.task_template_id == template_task.id)
        )
        saved_schedule = sched_result.scalar_one()
        assert saved_schedule.schedule_type == ScheduleType.cron
        assert saved_schedule.is_active is True
    
    async def test_retry_flow_with_queue(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test task retry flow through the queue."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create task
        task = Task(
            user_id=sample_user.id,
            task_type="retry_test",
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
        
        # First attempt - fail
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = agent.id
        task.status = TaskStatus.running
        await db_session.commit()
        
        # Fail and retry
        queue_entry.status = TaskStatus.pending
        queue_entry.retry_count = 1
        queue_entry.error_message = "Temporary failure"
        queue_entry.claimed_by = None
        task.status = TaskStatus.pending
        task.retry_count = 1
        await db_session.commit()
        
        # Second attempt - succeed
        queue_entry.status = TaskStatus.running
        queue_entry.claimed_by = agent.id
        task.status = TaskStatus.running
        await db_session.commit()
        
        queue_entry.status = TaskStatus.completed
        queue_entry.completed_at = datetime.now(timezone.utc)
        task.status = TaskStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        task.result = {"success": True}
        await db_session.commit()
        
        # Verify retry history
        await db_session.refresh(task)
        assert task.retry_count == 1
        assert task.status == TaskStatus.completed


# ============================================================================
# Test Scenario 4: Hierarchical Task Decomposition
# ============================================================================

class TestHierarchicalTaskDecomposition:
    """Test hierarchical task decomposition with dependencies."""
    
    async def test_nested_task_hierarchy(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test deeply nested task hierarchy."""
        # Create root task
        root = Task(
            user_id=sample_user.id,
            task_type="root_task",
            status=TaskStatus.pending,
        )
        db_session.add(root)
        await db_session.commit()
        await db_session.refresh(root)
        
        # Create level 1 children
        level1 = []
        for i in range(2):
            child = Task(
                user_id=sample_user.id,
                parent_task_id=root.id,
                task_type=f"level1_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(child)
            level1.append(child)
        await db_session.commit()
        for c in level1:
            await db_session.refresh(c)
        
        # Create level 2 children (grandchildren)
        level2 = []
        for parent in level1:
            for i in range(2):
                grandchild = Task(
                    user_id=sample_user.id,
                    parent_task_id=parent.id,
                    task_type=f"level2_task_{parent.task_type}_{i}",
                    status=TaskStatus.pending,
                )
                db_session.add(grandchild)
                level2.append(grandchild)
        await db_session.commit()
        
        # Verify hierarchy
        # Count children
        children_result = await db_session.execute(
            select(Task).where(Task.parent_task_id == root.id)
        )
        level1_saved = children_result.scalars().all()
        assert len(level1_saved) == 2
        
        # Count grandchildren
        grandchild_ids = [c.id for c in level1]
        grand_result = await db_session.execute(
            select(Task).where(Task.parent_task_id.in_(grandchild_ids))
        )
        level2_saved = grand_result.scalars().all()
        assert len(level2_saved) == 4  # 2 level1 * 2 children each
        
        # Verify cascade delete
        await db_session.delete(root)
        await db_session.commit()
        
        # All descendants should be deleted
        all_tasks = await db_session.execute(select(Task))
        assert len(all_tasks.all()) == 0
    
    async def test_dag_task_dependencies(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test DAG-style task dependencies."""
        # Create tasks
        tasks = []
        for i in range(5):
            task = Task(
                user_id=sample_user.id,
                task_type=f"dag_task_{i}",
                status=TaskStatus.pending,
            )
            db_session.add(task)
            tasks.append(task)
        await db_session.commit()
        for t in tasks:
            await db_session.refresh(t)
        
        # Create DAG dependencies:
        #     0
        #    /|\
        #   1 2 3
        #    \|/
        #     4
        deps = [
            (tasks[0].id, tasks[1].id),  # 0 -> 1
            (tasks[0].id, tasks[2].id),  # 0 -> 2
            (tasks[0].id, tasks[3].id),  # 0 -> 3
            (tasks[1].id, tasks[4].id),  # 1 -> 4
            (tasks[2].id, tasks[4].id),  # 2 -> 4
            (tasks[3].id, tasks[4].id),  # 3 -> 4
        ]
        
        for parent_id, child_id in deps:
            dep = TaskDependency(
                parent_task_id=parent_id,
                child_task_id=child_id,
                dependency_type=DependencyType.sequential,
            )
            db_session.add(dep)
        await db_session.commit()
        
        # Verify dependencies
        # Tasks 1, 2, 3 depend on task 0
        dep_0 = await db_session.execute(
            select(TaskDependency).where(TaskDependency.parent_task_id == tasks[0].id)
        )
        assert len(dep_0.all()) == 3
        
        # Task 4 depends on tasks 1, 2, 3
        dep_4 = await db_session.execute(
            select(TaskDependency).where(TaskDependency.child_task_id == tasks[4].id)
        )
        assert len(dep_4.all()) == 3


# ============================================================================
# Test Scenario 5: Cross-Module Data Integrity
# ============================================================================

class TestCrossModuleDataIntegrity:
    """Test data integrity across all modules."""
    
    async def test_complete_cascade_delete_chain(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentType,
    ):
        """Test that deleting user cascades through all related tables."""
        # Create user
        user = User(
            username=f"cascade_user_{uuid4().hex[:8]}",
            email=f"cascade_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create collaboration
        collab = CollaborationSession(
            user_id=user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create task
        task = Task(
            user_id=user.id,
            agent_id=agent.id,
            session_id=collab.session_id,
            task_type="cascade_test",
            status=TaskStatus.running,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        
        # Create tool and tool call
        tool = Tool(name=f"cascade_tool_{uuid4().hex[:8]}", is_active=True)
        db_session.add(tool)
        await db_session.commit()
        await db_session.refresh(tool)
        
        tool_call = ToolCall(
            task_id=task.id,
            tool_id=tool.id,
            status="completed",
        )
        db_session.add(tool_call)
        await db_session.commit()
        
        # Create token usage
        token_usage = TokenUsage(
            user_id=user.id,
            agent_id=agent.id,
            session_id=collab.session_id,
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.01"),
        )
        db_session.add(token_usage)
        await db_session.commit()
        
        # Create message
        msg = AgentMessage(
            collaboration_id=collab.id,
            sender_agent_id=agent.id,
            message_type=MessageType.request,
            content_json={"test": "data"},
        )
        db_session.add(msg)
        await db_session.commit()
        
        # Store IDs
        user_id = user.id
        agent_id = agent.id
        task_id = task.id
        collab_id = collab.id
        tool_call_id = tool_call.id
        token_usage_id = token_usage.id
        msg_id = msg.id
        
        # Delete user using raw SQL to bypass ORM relationship loading
        user_id_str = str(user.id)
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user_id_str}'")
        )
        await db_session.commit()
        
        # Verify cascade
        # User should be gone
        user_result = await db_session.execute(
            select(User).where(User.id == user_id)
        )
        assert user_result.scalar_one_or_none() is None
        
        # Agent should be gone (CASCADE)
        agent_result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.id == agent_id)
        )
        assert agent_result.scalar_one_or_none() is None
        
        # Task should be gone (CASCADE)
        task_result = await db_session.execute(
            select(Task).where(Task.id == task_id)
        )
        assert task_result.scalar_one_or_none() is None
        
        # Collaboration should be gone (CASCADE)
        collab_result = await db_session.execute(
            select(CollaborationSession).where(CollaborationSession.id == collab_id)
        )
        assert collab_result.scalar_one_or_none() is None
        
        # Tool call should be gone (CASCADE via task)
        tc_result = await db_session.execute(
            select(ToolCall).where(ToolCall.id == tool_call_id)
        )
        assert tc_result.scalar_one_or_none() is None
        
        # Token usage should be gone (CASCADE)
        tu_result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.id == token_usage_id)
        )
        assert tu_result.scalar_one_or_none() is None
        
        # Message should be gone (CASCADE)
        msg_result = await db_session.execute(
            select(AgentMessage).where(AgentMessage.id == msg_id)
        )
        assert msg_result.scalar_one_or_none() is None
        
        # Tool should still exist (not dependent on user)
        tool_result = await db_session.execute(
            select(Tool).where(Tool.id == tool.id)
        )
        assert tool_result.scalar_one_or_none() is not None
    
    async def test_audit_log_independence(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that audit logs are independent of user deletion."""
        # Create audit log entry
        result = await db_session.execute(
            text("""
                INSERT INTO audit.audit_log 
                (user_id, actor_type, actor_id, action, resource_type, resource_id, new_values)
                VALUES (:user_id, 'user', :actor_id, 'create', 'test_resource', :resource_id, '{}')
                RETURNING id
            """),
            {
                "user_id": str(sample_user.id),
                "actor_id": str(sample_user.id),
                "resource_id": str(uuid4()),
            },
        )
        audit_id = result.scalar()
        await db_session.commit()
        
        user_id = sample_user.id
        await db_session.execute(
            text(f"DELETE FROM users WHERE id = '{user_id}'")
        )
        await db_session.commit()
        
        # Audit log should still exist (no FK constraint, just a reference)
        audit_result = await db_session.execute(
            text("SELECT * FROM audit.audit_log WHERE id = :id"),
            {"id": str(audit_id)},
        )
        audit_row = audit_result.fetchone()
        assert audit_row is not None
        # user_id in audit should be preserved (it's just a UUID, not FK)


# ============================================================================
# Test Scenario 6: Error Handling and Constraint Enforcement
# ============================================================================

class TestErrorHandlingAndConstraints:
    """Test error handling and constraint enforcement across modules."""
    
    async def test_orphan_task_rejected(
        self,
        db_session: AsyncSession,
    ):
        """Test that task cannot be created without valid user."""
        fake_user_id = uuid4()
        task = Task(
            user_id=fake_user_id,
            task_type="orphan_task",
            status=TaskStatus.pending,
        )
        db_session.add(task)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_invalid_tool_call_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that tool call cannot be created without valid task and tool."""
        # Create tool but no task
        tool = Tool(name=f"test_tool_{uuid4().hex[:8]}", is_active=True)
        db_session.add(tool)
        await db_session.commit()
        await db_session.refresh(tool)
        
        fake_task_id = uuid4()
        tool_call = ToolCall(
            task_id=fake_task_id,
            tool_id=tool.id,
            status="pending",
        )
        db_session.add(tool_call)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_duplicate_session_id_rejected(
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
    
    async def test_duplicate_tool_name_rejected(
        self,
        db_session: AsyncSession,
    ):
        """Test that duplicate tool names are rejected."""
        tool_name = f"unique_tool_{uuid4().hex[:8]}"
        
        tool1 = Tool(name=tool_name, is_active=True)
        db_session.add(tool1)
        await db_session.commit()
        
        tool2 = Tool(name=tool_name, is_active=True)  # Duplicate
        db_session.add(tool2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()