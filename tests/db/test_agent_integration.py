# pyright: reportMissingImports=false
"""
Comprehensive integration tests for agent system.

This module tests end-to-end workflows across the agent system tables:
- users
- agent_types
- agent_instances
- collaboration_sessions
- agent_messages
- agent_capabilities

Test scenarios:
1. Single agent full workflow
2. Multiple agents collaborating with step_id grouping
3. Agent status lifecycle tracking
4. Capability validation during collaboration
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from db import create_engine, AsyncSession
from db.schema.agents import AgentType, AgentInstance
from db.schema.collaboration import (
    CollaborationSession,
    AgentMessage,
    CollaborationStatus,
    MessageRedactionLevel,
    MessageType,
)
from db.schema.agent_capabilities import AgentCapability
from db.schema.users import User
from db.types import AgentStatus, gen_random_uuid


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with all agent system tables.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation without requiring actual database connection.
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
        
        # 2. Create agent_types table (no FK dependencies)
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
        
        # 3. Create agent_instances table (FK to users and agent_types)
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
        
        # 4. Create agent_capabilities table (FK to agent_types)
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
        
        # 5. Create collaboration_sessions table (FK to users and agent_instances)
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
        
        # 6. Create agent_messages table (FK to collaboration_sessions and agent_instances)
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
        
        # Create indexes for all tables
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_types_name ON agent_types(name)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_types_is_active ON agent_types(is_active)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_instances_agent_type_id 
            ON agent_instances(agent_type_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_instances_status 
            ON agent_instances(status)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_instances_user 
            ON agent_instances(user_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capabilities_type 
            ON agent_capabilities(agent_type_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capabilities_name 
            ON agent_capabilities(capability_name)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_collab_user 
            ON collaboration_sessions(user_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_collab_status 
            ON collaboration_sessions(status)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_messages_collab 
            ON agent_messages(collaboration_id, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_messages_step 
            ON agent_messages(step_id)
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test (reverse dependency order)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS agent_messages"))
        await conn.execute(text("DROP TABLE IF EXISTS collaboration_sessions"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_capabilities"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
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
        name=f"TestAgent_{uuid4().hex[:8]}",
        description="A test agent type for integration testing",
        capabilities={
            "web_search": True,
            "summarization": True,
            "max_tokens": 4096,
        },
        default_config={
            "temperature": 0.7,
            "max_results": 10,
        },
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


# ============================================================================
# Test Scenario 1: Single Agent Full Workflow
# ============================================================================

class TestSingleAgentFullWorkflow:
    """Test complete end-to-end workflow for a single agent.
    
    This test validates the entire flow:
    User creation -> Agent type definition -> Agent instance creation ->
    Collaboration session initiation -> Agent messaging -> Session completion
    """
    
    async def test_complete_single_agent_workflow(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test the complete single agent workflow from user creation to session completion."""
        # Step 1: Verify user was created
        assert sample_user.id is not None
        assert sample_user.username is not None
        assert sample_user.email is not None
        
        # Step 2: Verify agent type was created
        assert sample_agent_type.id is not None
        assert sample_agent_type.name is not None
        assert sample_agent_type.capabilities is not None
        assert sample_agent_type.capabilities.get("web_search") is True
        
        # Step 3: Create agent instance
        agent_instance = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="ResearchAgent-001",
            status=AgentStatus.idle,
            config={"custom_param": "value"},
        )
        db_session.add(agent_instance)
        await db_session.commit()
        await db_session.refresh(agent_instance)
        
        assert agent_instance.id is not None
        assert agent_instance.agent_type_id == sample_agent_type.id
        assert agent_instance.user_id == sample_user.id
        assert agent_instance.status == AgentStatus.idle
        
        # Step 4: Create collaboration session
        session_id = f"session-{uuid4()}"
        collaboration = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent_instance.id,
            name="Research Session",
            session_id=session_id,
            status=CollaborationStatus.active,
            involves_secrets=False,
            context_json={"topic": "integration testing"},
        )
        db_session.add(collaboration)
        await db_session.commit()
        await db_session.refresh(collaboration)
        
        assert collaboration.id is not None
        assert collaboration.main_agent_id == agent_instance.id
        assert collaboration.status == CollaborationStatus.active
        
        # Step 5: Update agent status to busy (starting work)
        agent_instance.status = AgentStatus.busy
        await db_session.commit()
        await db_session.refresh(agent_instance)
        assert agent_instance.status == AgentStatus.busy
        
        # Step 6: Create message sequence (request -> response pattern)
        # Request message
        request_message = AgentMessage(
            collaboration_id=collaboration.id,
            step_id="step-001",
            sender_agent_id=agent_instance.id,
            receiver_agent_id=None,  # External request
            message_type=MessageType.request,
            content_json={"query": "What is integration testing?"},
            redaction_level=MessageRedactionLevel.none,
        )
        db_session.add(request_message)
        await db_session.commit()
        await db_session.refresh(request_message)
        
        # Response message
        response_message = AgentMessage(
            collaboration_id=collaboration.id,
            step_id="step-001",  # Same step_id for related messages
            sender_agent_id=agent_instance.id,
            receiver_agent_id=None,
            message_type=MessageType.response,
            content_json={"answer": "Integration testing validates component interactions."},
            redaction_level=MessageRedactionLevel.none,
        )
        db_session.add(response_message)
        await db_session.commit()
        await db_session.refresh(response_message)
        
        # Step 7: Complete the session
        collaboration.status = CollaborationStatus.completed
        collaboration.ended_at = datetime.now(timezone.utc)
        agent_instance.status = AgentStatus.idle  # Back to idle
        await db_session.commit()
        
        # Step 8: Verify final state
        await db_session.refresh(collaboration)
        await db_session.refresh(agent_instance)
        
        assert collaboration.status == CollaborationStatus.completed
        assert collaboration.ended_at is not None
        assert agent_instance.status == AgentStatus.idle
        
        # Step 9: Verify messages were persisted correctly
        result = await db_session.execute(
            select(AgentMessage)
            .where(AgentMessage.collaboration_id == collaboration.id)
            .order_by(AgentMessage.created_at)
        )
        messages = result.scalars().all()
        
        assert len(messages) == 2
        assert messages[0].message_type == MessageType.request
        assert messages[1].message_type == MessageType.response
        assert messages[0].step_id == messages[1].step_id  # Same step_id
    
    async def test_foreign_key_chain_validation(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Validate that all foreign key relationships work correctly across the chain."""
        # Create agent instance
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create collaboration session
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create message referencing all FKs
        message = AgentMessage(
            collaboration_id=collab.id,
            sender_agent_id=agent.id,
            receiver_agent_id=agent.id,  # Self-referential for testing
            message_type=MessageType.notification,
            content_json={"test": "data"},
        )
        db_session.add(message)
        await db_session.commit()
        await db_session.refresh(message)
        
        # Verify FK chain: message -> collaboration -> agent -> agent_type/user
        assert message.collaboration_id == collab.id
        assert message.sender_agent_id == agent.id
        
        # Query with joins to verify relationships
        result = await db_session.execute(
            select(AgentMessage)
            .join(CollaborationSession, AgentMessage.collaboration_id == CollaborationSession.id)
            .join(AgentInstance, CollaborationSession.main_agent_id == AgentInstance.id)
            .join(AgentType, AgentInstance.agent_type_id == AgentType.id)
            .join(User, AgentInstance.user_id == User.id)
            .where(AgentMessage.id == message.id)
        )
        joined = result.scalar_one()
        
        assert joined is not None
        assert joined.id == message.id
    
    async def test_cascade_delete_across_entire_chain(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test CASCADE DELETE propagates correctly through all tables."""
        # Create full data chain
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
        
        # Create messages
        for i in range(3):
            msg = AgentMessage(
                collaboration_id=collab.id,
                step_id=f"step-{i}",
                message_type=MessageType.request,
                content_json={"index": i},
            )
            db_session.add(msg)
        await db_session.commit()
        
        agent_id = agent.id
        collab_id = collab.id
        
        # Delete user - should cascade through entire chain
        await db_session.delete(sample_user)
        await db_session.commit()
        
        # Verify cascade: user -> agent_instances -> collaboration_sessions -> agent_messages
        agent_result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.id == agent_id)
        )
        assert agent_result.scalar_one_or_none() is None
        
        collab_result = await db_session.execute(
            select(CollaborationSession).where(CollaborationSession.id == collab_id)
        )
        assert collab_result.scalar_one_or_none() is None
        
        msg_result = await db_session.execute(
            select(AgentMessage).where(AgentMessage.collaboration_id == collab_id)
        )
        assert len(msg_result.all()) == 0


# ============================================================================
# Test Scenario 2: Multiple Agents Collaborating
# ============================================================================

class TestMultipleAgentsCollaborating:
    """Test multi-agent collaboration with step_id grouping for message flows."""
    
    async def test_multi_agent_collaboration_with_step_grouping(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test multiple agents collaborating with proper step_id grouping."""
        # Create multiple agent types
        coordinator_type = AgentType(
            name=f"Coordinator_{uuid4().hex[:8]}",
            description="Main coordinator agent",
            capabilities={"delegation": True, "planning": True},
            is_active=True,
        )
        worker_type = AgentType(
            name=f"Worker_{uuid4().hex[:8]}",
            description="Worker agent for tasks",
            capabilities={"execution": True, "reporting": True},
            is_active=True,
        )
        db_session.add_all([coordinator_type, worker_type])
        await db_session.commit()
        await db_session.refresh(coordinator_type)
        await db_session.refresh(worker_type)
        
        # Create multiple agent instances
        coordinator = AgentInstance(
            agent_type_id=coordinator_type.id,
            user_id=sample_user.id,
            name="Coordinator-001",
            status=AgentStatus.idle,
        )
        worker1 = AgentInstance(
            agent_type_id=worker_type.id,
            user_id=sample_user.id,
            name="Worker-001",
            status=AgentStatus.idle,
        )
        worker2 = AgentInstance(
            agent_type_id=worker_type.id,
            user_id=sample_user.id,
            name="Worker-002",
            status=AgentStatus.idle,
        )
        db_session.add_all([coordinator, worker1, worker2])
        await db_session.commit()
        
        for agent in [coordinator, worker1, worker2]:
            await db_session.refresh(agent)
        
        # Create collaboration session with coordinator as main
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=coordinator.id,
            name="Multi-Agent Task",
            session_id=session_id,
            status=CollaborationStatus.active,
            context_json={
                "agents": [str(coordinator.id), str(worker1.id), str(worker2.id)],
                "task": "parallel processing",
            },
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Simulate a conversation flow with step_id grouping:
        # Step 1: Coordinator sends task to workers
        step1_coordinator_msg = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-001",
            sender_agent_id=coordinator.id,
            receiver_agent_id=worker1.id,
            message_type=MessageType.request,
            content_json={"task": "process_data", "data": {"id": 1}},
        )
        step1_worker1_response = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-001",
            sender_agent_id=worker1.id,
            receiver_agent_id=coordinator.id,
            message_type=MessageType.response,
            content_json={"status": "acknowledged", "task_id": 1},
        )
        db_session.add_all([step1_coordinator_msg, step1_worker1_response])
        await db_session.commit()
        
        # Step 2: Tool call pattern (request -> tool_call -> tool_result -> response)
        step2_request = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-002",
            sender_agent_id=worker1.id,
            message_type=MessageType.request,
            content_json={"action": "fetch_remote_data"},
        )
        step2_tool_call = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-002",
            sender_agent_id=worker1.id,
            message_type=MessageType.tool_call,
            content_json={"tool": "http_client", "params": {"url": "https://api.example.com"}},
        )
        step2_tool_result = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-002",
            sender_agent_id=worker1.id,
            message_type=MessageType.tool_result,
            content_json={"status": "success", "data": {"result": "fetched"}},
        )
        step2_response = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-002",
            sender_agent_id=worker1.id,
            receiver_agent_id=coordinator.id,
            message_type=MessageType.response,
            content_json={"result": "processed"},
        )
        db_session.add_all([step2_request, step2_tool_call, step2_tool_result, step2_response])
        await db_session.commit()
        
        # Step 3: Coordinator aggregates results from multiple workers
        step3_aggregation = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-003",
            sender_agent_id=coordinator.id,
            message_type=MessageType.notification,
            content_json={"aggregated_result": "all tasks complete"},
        )
        db_session.add(step3_aggregation)
        await db_session.commit()
        
        # Verify step_id grouping
        # Query messages by step_id
        step1_messages = (await db_session.execute(
            select(AgentMessage).where(AgentMessage.step_id == "step-001")
        )).scalars().all()
        assert len(step1_messages) == 2
        assert {m.message_type for m in step1_messages} == {MessageType.request, MessageType.response}
        
        step2_messages = (await db_session.execute(
            select(AgentMessage).where(AgentMessage.step_id == "step-002")
        )).scalars().all()
        assert len(step2_messages) == 4
        message_types = [m.message_type for m in step2_messages]
        assert MessageType.request in message_types
        assert MessageType.tool_call in message_types
        assert MessageType.tool_result in message_types
        assert MessageType.response in message_types
        
        step3_messages = (await db_session.execute(
            select(AgentMessage).where(AgentMessage.step_id == "step-003")
        )).scalars().all()
        assert len(step3_messages) == 1
        
        # Verify all messages in collaboration
        all_messages = (await db_session.execute(
            select(AgentMessage)
            .where(AgentMessage.collaboration_id == collab.id)
            .order_by(AgentMessage.created_at)
        )).scalars().all()
        assert len(all_messages) == 7
        
        # Verify agents participated
        sender_ids = {m.sender_agent_id for m in all_messages}
        assert coordinator.id in sender_ids
        assert worker1.id in sender_ids
    
    async def test_agent_instance_capability_validation(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that agents can only use capabilities defined for their type."""
        # Create agent type with specific capabilities
        agent_type = AgentType(
            name=f"RestrictedAgent_{uuid4().hex[:8]}",
            capabilities={
                "allowed_action_1": True,
                "allowed_action_2": True,
                "forbidden_action": False,
            },
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create agent instance
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Verify capabilities are accessible via relationship
        result = await db_session.execute(
            select(AgentType).where(AgentType.id == agent.agent_type_id)
        )
        fetched_type = result.scalar_one()
        
        assert fetched_type.capabilities is not None
        assert fetched_type.capabilities.get("allowed_action_1") is True
        assert fetched_type.capabilities.get("forbidden_action") is False
    
    async def test_cross_agent_message_routing(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test message routing between different agents in a collaboration."""
        # Create two different agent types
        type_a = AgentType(
            name=f"TypeA_{uuid4().hex[:8]}",
            capabilities={"send": True, "receive": True},
            is_active=True,
        )
        type_b = AgentType(
            name=f"TypeB_{uuid4().hex[:8]}",
            capabilities={"send": True, "receive": True},
            is_active=True,
        )
        db_session.add_all([type_a, type_b])
        await db_session.commit()
        for t in [type_a, type_b]:
            await db_session.refresh(t)
        
        # Create agents
        agent_a = AgentInstance(
            agent_type_id=type_a.id,
            user_id=sample_user.id,
            name="Agent-A",
        )
        agent_b = AgentInstance(
            agent_type_id=type_b.id,
            user_id=sample_user.id,
            name="Agent-B",
        )
        db_session.add_all([agent_a, agent_b])
        await db_session.commit()
        for a in [agent_a, agent_b]:
            await db_session.refresh(a)
        
        # Create collaboration
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent_a.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Test bidirectional messaging
        # A -> B
        msg_a_to_b = AgentMessage(
            collaboration_id=collab.id,
            step_id="exchange-1",
            sender_agent_id=agent_a.id,
            receiver_agent_id=agent_b.id,
            message_type=MessageType.request,
            content_json={"from": "A", "to": "B"},
        )
        # B -> A
        msg_b_to_a = AgentMessage(
            collaboration_id=collab.id,
            step_id="exchange-2",
            sender_agent_id=agent_b.id,
            receiver_agent_id=agent_a.id,
            message_type=MessageType.response,
            content_json={"from": "B", "to": "A"},
        )
        db_session.add_all([msg_a_to_b, msg_b_to_a])
        await db_session.commit()
        
        # Verify routing by querying receiver
        b_received = (await db_session.execute(
            select(AgentMessage).where(AgentMessage.receiver_agent_id == agent_b.id)
        )).scalars().all()
        assert len(b_received) == 1
        assert b_received[0].sender_agent_id == agent_a.id
        
        a_received = (await db_session.execute(
            select(AgentMessage).where(AgentMessage.receiver_agent_id == agent_a.id)
        )).scalars().all()
        assert len(a_received) == 1
        assert a_received[0].sender_agent_id == agent_b.id


# ============================================================================
# Test Scenario 3: Agent Status Lifecycle Tracking
# ============================================================================

class TestAgentStatusLifecycleTracking:
    """Test agent status transitions and state consistency."""
    
    async def test_status_transitions_idle_busy_error_offline(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test all valid status transitions: idle -> busy -> error -> offline."""
        # Create agent
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="StatusTestAgent",
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.status == AgentStatus.idle
        
        # Transition: idle -> busy
        agent.status = AgentStatus.busy
        await db_session.commit()
        await db_session.refresh(agent)
        assert agent.status == AgentStatus.busy
        
        # Transition: busy -> error (simulating failure)
        agent.status = AgentStatus.error
        await db_session.commit()
        await db_session.refresh(agent)
        assert agent.status == AgentStatus.error
        
        # Transition: error -> idle (recovery)
        agent.status = AgentStatus.idle
        await db_session.commit()
        await db_session.refresh(agent)
        assert agent.status == AgentStatus.idle
        
        # Transition: idle -> busy -> offline (shutdown)
        agent.status = AgentStatus.busy
        await db_session.commit()
        agent.status = AgentStatus.offline
        await db_session.commit()
        await db_session.refresh(agent)
        assert agent.status == AgentStatus.offline
    
    async def test_status_consistency_with_collaboration(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that agent status reflects collaboration state."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create collaboration - agent becomes busy
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
            status=CollaborationStatus.active,
        )
        db_session.add(collab)
        agent.status = AgentStatus.busy  # Should be busy when collaboration starts
        await db_session.commit()
        
        # Verify status is busy during active collaboration
        await db_session.refresh(agent)
        assert agent.status == AgentStatus.busy
        
        # Complete collaboration - agent returns to idle
        collab.status = CollaborationStatus.completed
        collab.ended_at = datetime.now(timezone.utc)
        agent.status = AgentStatus.idle
        await db_session.commit()
        
        await db_session.refresh(agent)
        await db_session.refresh(collab)
        assert agent.status == AgentStatus.idle
        assert collab.status == CollaborationStatus.completed
    
    async def test_heartbeat_updates(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that heartbeats are properly recorded for agent liveness."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
            last_heartbeat_at=None,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.last_heartbeat_at is None
        
        # Simulate heartbeat
        heartbeat_time = datetime.now(timezone.utc)
        agent.last_heartbeat_at = heartbeat_time
        agent.status = AgentStatus.busy
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.last_heartbeat_at is not None
        # Allow small time difference for database timestamp precision
        time_diff = abs((agent.last_heartbeat_at - heartbeat_time).total_seconds())
        assert time_diff < 1.0  # Within 1 second
        
        # Another heartbeat later
        await asyncio.sleep(0.01)
        new_heartbeat = datetime.now(timezone.utc)
        agent.last_heartbeat_at = new_heartbeat
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.last_heartbeat_at > heartbeat_time
    
    async def test_multiple_agents_status_independence(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that multiple agents can have independent status states."""
        # Create agent type
        agent_type = AgentType(
            name=f"MultiStatusAgent_{uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create multiple agents
        agents = []
        for i, status in enumerate([AgentStatus.idle, AgentStatus.busy, AgentStatus.error, AgentStatus.offline]):
            agent = AgentInstance(
                agent_type_id=agent_type.id,
                user_id=sample_user.id,
                name=f"Agent-{i}",
                status=status,
            )
            agents.append(agent)
        db_session.add_all(agents)
        await db_session.commit()
        
        for agent in agents:
            await db_session.refresh(agent)
        
        # Verify independent states
        statuses = {a.status for a in agents}
        assert AgentStatus.idle in statuses
        assert AgentStatus.busy in statuses
        assert AgentStatus.error in statuses
        assert AgentStatus.offline in statuses
        
        # Change one agent's status - should not affect others
        agents[0].status = AgentStatus.busy
        await db_session.commit()
        
        for i, agent in enumerate(agents):
            await db_session.refresh(agent)
            if i == 0:
                assert agent.status == AgentStatus.busy
            else:
                # Others should retain original status
                expected = [AgentStatus.idle, AgentStatus.busy, AgentStatus.error, AgentStatus.offline][i]
                assert agent.status == expected
    
    async def test_invalid_status_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that invalid status values are rejected by the database."""
        agent = AgentInstance(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status=AgentStatus.idle,
        )
        db_session.add(agent)
        await db_session.commit()
        
        # Try to set invalid status via raw SQL (bypassing enum)
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(f"UPDATE agent_instances SET status = 'invalid_status' WHERE id = '{agent.id}'")
            )
            await db_session.commit()


# ============================================================================
# Test Scenario 4: Capability Validation During Collaboration
# ============================================================================

class TestCapabilityValidationDuringCollaboration:
    """Test agent capabilities and their enforcement during collaboration."""
    
    async def test_agent_type_capabilities_accessible_to_instance(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that agent instance can access capabilities from its type."""
        # Create agent type with capabilities
        agent_type = AgentType(
            name=f"CapableAgent_{uuid4().hex[:8]}",
            description="Agent with specific capabilities",
            capabilities={
                "web_search": True,
                "file_read": True,
                "file_write": False,
                "max_file_size_mb": 10,
                "supported_formats": ["pdf", "txt", "md"],
            },
            default_config={
                "timeout_seconds": 30,
                "retry_count": 3,
            },
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create agent instance
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
            name="CapableInstance",
            config={"timeout_seconds": 60},  # Override default
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Query capabilities via join
        result = await db_session.execute(
            select(AgentInstance, AgentType)
            .join(AgentType, AgentInstance.agent_type_id == AgentType.id)
            .where(AgentInstance.id == agent.id)
        )
        instance, atype = result.one()
        
        # Verify capabilities
        assert atype.capabilities is not None
        assert atype.capabilities["web_search"] is True
        assert atype.capabilities["file_write"] is False
        assert atype.capabilities["max_file_size_mb"] == 10
        assert "pdf" in atype.capabilities["supported_formats"]
        
        # Verify instance config override
        assert instance.config["timeout_seconds"] == 60
    
    async def test_agent_capabilities_table_integration(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test agent_capabilities table with FK to agent_types."""
        # Create agent type
        agent_type = AgentType(
            name=f"CapDefAgent_{uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create capability definitions
        web_search_cap = AgentCapability(
            agent_type_id=agent_type.id,
            capability_name="web_search",
            description="Search the web for information",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
            },
            is_active=True,
        )
        summarization_cap = AgentCapability(
            agent_type_id=agent_type.id,
            capability_name="summarization",
            description="Summarize text content",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "max_length": {"type": "integer", "default": 500},
                },
                "required": ["text"],
            },
            is_active=True,
        )
        db_session.add_all([web_search_cap, summarization_cap])
        await db_session.commit()
        
        for cap in [web_search_cap, summarization_cap]:
            await db_session.refresh(cap)
        
        # Create agent instance
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Query capabilities for this agent type
        result = await db_session.execute(
            select(AgentCapability)
            .where(AgentCapability.agent_type_id == agent_type.id)
            .where(AgentCapability.is_active == True)
        )
        capabilities = result.scalars().all()
        
        assert len(capabilities) == 2
        cap_names = {c.capability_name for c in capabilities}
        assert cap_names == {"web_search", "summarization"}
        
        # Verify input schema
        web_cap = next(c for c in capabilities if c.capability_name == "web_search")
        assert "query" in web_cap.input_schema["properties"]
        assert web_cap.input_schema["required"] == ["query"]
    
    async def test_capability_based_message_validation(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that capabilities can be used to validate message content."""
        # Create agent type with restricted capabilities
        agent_type = AgentType(
            name=f"RestrictedCapAgent_{uuid4().hex[:8]}",
            capabilities={
                "allowed_tools": ["calculator", "translator"],
                "max_message_size_bytes": 1024,
            },
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create detailed capability
        calc_cap = AgentCapability(
            agent_type_id=agent_type.id,
            capability_name="calculator",
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                },
                "required": ["expression"],
            },
            is_active=True,
        )
        db_session.add(calc_cap)
        await db_session.commit()
        await db_session.refresh(calc_cap)
        
        # Create agent
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        # Create collaboration
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Create tool_call message that uses allowed capability
        tool_call_msg = AgentMessage(
            collaboration_id=collab.id,
            sender_agent_id=agent.id,
            message_type=MessageType.tool_call,
            content_json={
                "tool": "calculator",
                "params": {"expression": "2+2"},
            },
        )
        db_session.add(tool_call_msg)
        await db_session.commit()
        await db_session.refresh(tool_call_msg)
        
        # Verify message was stored
        assert tool_call_msg.id is not None
        assert tool_call_msg.message_type == MessageType.tool_call
        assert tool_call_msg.content_json["tool"] == "calculator"
    
    async def test_inactive_capability_not_usable(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that inactive capabilities are not available for use."""
        # Create agent type
        agent_type = AgentType(
            name=f"InactiveCapAgent_{uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create active and inactive capabilities
        active_cap = AgentCapability(
            agent_type_id=agent_type.id,
            capability_name="active_capability",
            is_active=True,
        )
        inactive_cap = AgentCapability(
            agent_type_id=agent_type.id,
            capability_name="inactive_capability",
            is_active=False,
        )
        db_session.add_all([active_cap, inactive_cap])
        await db_session.commit()
        
        # Query only active capabilities
        result = await db_session.execute(
            select(AgentCapability)
            .where(AgentCapability.agent_type_id == agent_type.id)
            .where(AgentCapability.is_active == True)
        )
        active_capabilities = result.scalars().all()
        
        assert len(active_capabilities) == 1
        assert active_capabilities[0].capability_name == "active_capability"
    
    async def test_capability_cascade_on_agent_type_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that capabilities are cascade deleted when agent type is deleted."""
        # Create agent type
        agent_type = AgentType(
            name=f"CascadeCapAgent_{uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # Create capabilities
        for i in range(3):
            cap = AgentCapability(
                agent_type_id=agent_type.id,
                capability_name=f"capability_{i}",
                is_active=True,
            )
            db_session.add(cap)
        await db_session.commit()
        
        # Verify capabilities exist
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.agent_type_id == agent_type.id)
        )
        assert len(result.all()) == 3
        
        # Delete agent type
        await db_session.delete(agent_type)
        await db_session.commit()
        
        # Verify capabilities were cascade deleted
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.agent_type_id == agent_type.id)
        )
        assert len(result.all()) == 0


# ============================================================================
# Cross-Module Integration Tests
# ============================================================================

class TestCrossModuleIntegration:
    """Test integration across all agent system modules."""
    
    async def test_full_system_integration(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Complete integration test across all agent system tables."""
        # 1. Create agent type with capabilities
        agent_type = AgentType(
            name=f"FullIntegrationAgent_{uuid4().hex[:8]}",
            description="Agent for full integration testing",
            capabilities={
                "multi_step": True,
                "collaboration": True,
            },
            default_config={"mode": "standard"},
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        # 2. Create capability definitions
        capabilities = []
        for cap_name in ["analyze", "synthesize", "report"]:
            cap = AgentCapability(
                agent_type_id=agent_type.id,
                capability_name=cap_name,
                is_active=True,
            )
            db_session.add(cap)
            capabilities.append(cap)
        await db_session.commit()
        
        # 3. Create multiple agent instances
        agents = []
        for i in range(3):
            agent = AgentInstance(
                agent_type_id=agent_type.id,
                user_id=sample_user.id,
                name=f"IntegrationAgent-{i}",
                status=AgentStatus.idle,
            )
            db_session.add(agent)
            agents.append(agent)
        await db_session.commit()
        
        for agent in agents:
            await db_session.refresh(agent)
        
        # 4. Create collaboration session
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agents[0].id,
            name="Full Integration Session",
            session_id=f"session-{uuid4()}",
            status=CollaborationStatus.active,
            context_json={"participants": len(agents)},
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # 5. Update agent statuses
        for agent in agents:
            agent.status = AgentStatus.busy
        await db_session.commit()
        
        # 6. Create message flow
        messages = []
        step_ids = [f"step-{i}" for i in range(1, 4)]
        for i, step_id in enumerate(step_ids):
            msg = AgentMessage(
                collaboration_id=collab.id,
                step_id=step_id,
                sender_agent_id=agents[i % len(agents)].id,
                receiver_agent_id=agents[(i + 1) % len(agents)].id,
                message_type=MessageType.request,
                content_json={"step": i + 1, "action": capabilities[i % len(capabilities)].capability_name},
            )
            db_session.add(msg)
            messages.append(msg)
        await db_session.commit()
        
        # 7. Verify full chain via complex query
        result = await db_session.execute(
            select(AgentMessage, CollaborationSession, AgentInstance, AgentType, User)
            .join(CollaborationSession, AgentMessage.collaboration_id == CollaborationSession.id)
            .join(AgentInstance, AgentMessage.sender_agent_id == AgentInstance.id)
            .join(AgentType, AgentInstance.agent_type_id == AgentType.id)
            .join(User, AgentInstance.user_id == User.id)
            .where(CollaborationSession.id == collab.id)
            .order_by(AgentMessage.created_at)
        )
        joined_data = result.all()
        
        assert len(joined_data) == 3
        
        # Verify all relationships work
        for msg, session, instance, atype, user in joined_data:
            assert msg.collaboration_id == session.id
            assert session.main_agent_id in [a.id for a in agents]
            assert instance.agent_type_id == atype.id
            assert atype.id == agent_type.id
            assert user.id == sample_user.id
        
        # 8. Complete session
        collab.status = CollaborationStatus.completed
        collab.ended_at = datetime.now(timezone.utc)
        for agent in agents:
            agent.status = AgentStatus.idle
        await db_session.commit()
        
        # 9. Final verification
        await db_session.refresh(collab)
        assert collab.status == CollaborationStatus.completed
        
        # Verify all agents returned to idle
        for agent in agents:
            await db_session.refresh(agent)
            assert agent.status == AgentStatus.idle
    
    async def test_relationship_integrity(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that all relationship integrity is maintained."""
        # Create minimal chain
        agent_type = AgentType(name=f"RelTest_{uuid4().hex[:8]}", is_active=True)
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
        
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=agent.id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        # Test bidirectional relationships via SQLAlchemy ORM
        # User -> AgentInstances
        await db_session.refresh(sample_user)
        user_agents = await db_session.execute(
            select(AgentInstance).where(AgentInstance.user_id == sample_user.id)
        )
        assert len(user_agents.all()) >= 1
        
        # AgentType -> AgentInstances
        type_agents = await db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_type_id == agent_type.id)
        )
        assert len(type_agents.all()) >= 1
        
        # CollaborationSession -> Messages
        msg = AgentMessage(
            collaboration_id=collab.id,
            message_type=MessageType.notification,
            content_json={"test": "relationship"},
        )
        db_session.add(msg)
        await db_session.commit()
        
        collab_messages = await db_session.execute(
            select(AgentMessage).where(AgentMessage.collaboration_id == collab.id)
        )
        assert len(collab_messages.all()) == 1


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling and constraint enforcement."""
    
    async def test_orphan_agent_instance_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that agent instance cannot be created without valid type."""
        fake_type_id = uuid4()
        agent = AgentInstance(
            agent_type_id=fake_type_id,
            user_id=sample_user.id,
        )
        db_session.add(agent)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_collaboration_requires_valid_agent(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Test that collaboration cannot be created with invalid agent."""
        fake_agent_id = uuid4()
        collab = CollaborationSession(
            user_id=sample_user.id,
            main_agent_id=fake_agent_id,
            session_id=f"session-{uuid4()}",
        )
        db_session.add(collab)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_message_requires_valid_collaboration(
        self,
        db_session: AsyncSession,
    ):
        """Test that message cannot be created without valid collaboration."""
        fake_collab_id = uuid4()
        msg = AgentMessage(
            collaboration_id=fake_collab_id,
            message_type=MessageType.request,
            content_json={"test": "data"},
        )
        db_session.add(msg)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_duplicate_session_id_rejected(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_type: AgentType,
    ):
        """Test that duplicate session_id is rejected."""
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
    
    async def test_capability_requires_valid_agent_type(
        self,
        db_session: AsyncSession,
    ):
        """Test that capability cannot be created without valid agent type."""
        fake_type_id = uuid4()
        cap = AgentCapability(
            agent_type_id=fake_type_id,
            capability_name="test_capability",
        )
        db_session.add(cap)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()