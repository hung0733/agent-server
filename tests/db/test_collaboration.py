# pyright: reportMissingImports=false
"""
Tests for collaboration database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, cascade behavior, and JSONB validation for
collaboration_sessions and agent_messages tables.
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
from db.schema.collaboration import CollaborationSession, AgentMessage, CollaborationStatus, MessageRedactionLevel, MessageType


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
        
        # Create agent_types table
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
        
        # Create agent_instances table with FK constraints
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
        
        # Create collaboration_sessions table
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
        
        # Create agent_messages table
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
        
        # Create indexes for collaboration_sessions
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_collab_user 
            ON collaboration_sessions(user_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_collab_status 
            ON collaboration_sessions(status)
        """))
        
        # Create indexes for agent_messages
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
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS agent_messages"))
        await conn.execute(text("DROP TABLE IF EXISTS collaboration_sessions"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestCollaborationSessionSchema:
    """Test collaboration_sessions schema creation and structure."""
    
    async def test_collaboration_sessions_table_exists(self, db_session: AsyncSession):
        """Test that the collaboration_sessions table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'collaboration_sessions'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "collaboration_sessions"
    
    async def test_collaboration_sessions_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in collaboration_sessions table."""
        expected_columns = {
            'id', 'user_id', 'main_agent_id', 'name', 'session_id',
            'status', 'involves_secrets', 'context_json', 'created_at',
            'ended_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'collaboration_sessions'
                ORDER BY ordinal_position
            """)
        )
        columns = {row.column_name for row in result.all()}
        
        assert columns == expected_columns
    
    async def test_collaboration_sessions_indexes_exist(self, db_session: AsyncSession):
        """Test that required indexes exist on collaboration_sessions."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'collaboration_sessions'
            """)
        )
        indexes = {row.indexname for row in result.all()}
        
        # Check for required indexes
        assert 'idx_collab_user' in indexes
        assert 'idx_collab_status' in indexes
    
    async def test_collaboration_sessions_unique_constraint(self, db_session: AsyncSession):
        """Test that unique constraint on session_id exists."""
        result = await db_session.execute(
            text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'collaboration_sessions' 
                AND constraint_type = 'UNIQUE'
            """)
        )
        constraints = {row.constraint_name for row in result.all()}
        
        assert 'uq_collaboration_sessions_session_id' in constraints
    
    async def test_collaboration_sessions_check_constraint(self, db_session: AsyncSession):
        """Test that CHECK constraint on status exists."""
        result = await db_session.execute(
            text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'collaboration_sessions' 
                AND constraint_type = 'CHECK'
            """)
        )
        constraints = {row.constraint_name for row in result.all()}
        
        assert 'ck_collaboration_sessions_status' in constraints


class TestAgentMessageSchema:
    """Test agent_messages schema creation and structure."""
    
    async def test_agent_messages_table_exists(self, db_session: AsyncSession):
        """Test that the agent_messages table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'agent_messages'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "agent_messages"
    
    async def test_agent_messages_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in agent_messages table."""
        expected_columns = {
            'id', 'collaboration_id', 'step_id', 'sender_agent_id',
            'receiver_agent_id', 'message_type', 'content_json',
            'redaction_level', 'created_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agent_messages'
                ORDER BY ordinal_position
            """)
        )
        columns = {row.column_name for row in result.all()}
        
        assert columns == expected_columns
    
    async def test_agent_messages_indexes_exist(self, db_session: AsyncSession):
        """Test that required indexes exist on agent_messages."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'agent_messages'
            """)
        )
        indexes = {row.indexname for row in result.all()}
        
        # Check for required indexes
        assert 'idx_messages_collab' in indexes
        assert 'idx_messages_step' in indexes
    
    async def test_agent_messages_check_constraints(self, db_session: AsyncSession):
        """Test that CHECK constraints exist on agent_messages."""
        result = await db_session.execute(
            text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'agent_messages' 
                AND constraint_type = 'CHECK'
            """)
        )
        constraints = {row.constraint_name for row in result.all()}
        
        assert 'ck_agent_messages_message_type' in constraints
        assert 'ck_agent_messages_redaction_level' in constraints


class TestCollaborationSessionCRUD:
    """Test CRUD operations for collaboration sessions."""
    
    async def test_create_collaboration_session(self, db_session: AsyncSession):
        """Test creating a collaboration session."""
        # Create user and agent first
        user_result = await db_session.execute(
            text("""
                INSERT INTO users (username, email) 
                VALUES ('testuser', 'test@example.com')
                RETURNING id
            """)
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("""
                INSERT INTO agent_types (name) 
                VALUES ('TestAgent')
                RETURNING id
            """)
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            name="Test Collaboration",
            session_id=session_id,
            status="active",
            involves_secrets=False,
            context_json={"topic": "test"},
        )
        
        db_session.add(collab)
        await db_session.commit()
        await db_session.refresh(collab)
        
        assert collab.id is not None
        assert collab.user_id == user_id
        assert collab.main_agent_id == agent_id
        assert collab.session_id == session_id
        assert collab.status == "active"
        assert collab.context_json == {"topic": "test"}
    
    async def test_update_collaboration_session(self, db_session: AsyncSession):
        """Test updating a collaboration session."""
        # Create user, agent, and session
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('testuser2', 'test2@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('TestAgent2') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            name="Original Name",
            session_id=session_id,
            status="active",
        )
        
        db_session.add(collab)
        await db_session.commit()
        
        # Update
        collab.name = "Updated Name"
        collab.status = "completed"
        await db_session.commit()
        
        await db_session.refresh(collab)
        assert collab.name == "Updated Name"
        assert collab.status == "completed"
    
    async def test_delete_collaboration_session(self, db_session: AsyncSession):
        """Test deleting a collaboration session."""
        # Create user, agent, and session
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('testuser3', 'test3@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('TestAgent3') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        
        db_session.add(collab)
        await db_session.commit()
        
        # Delete
        await db_session.delete(collab)
        await db_session.commit()
        
        # Verify deletion
        result = await db_session.execute(
            select(CollaborationSession).where(CollaborationSession.id == collab.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_session_id_unique_constraint(self, db_session: AsyncSession):
        """Test that session_id is unique."""
        # Create user and agent
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('testuser4', 'test4@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('TestAgent4') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        
        # Create first session
        collab1 = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab1)
        await db_session.commit()
        
        # Try to create another with same session_id
        collab2 = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_status_enum_values(self, db_session: AsyncSession):
        """Test that status enum values are valid."""
        # Verify enum values match database constraint
        assert CollaborationStatus.active.value == "active"
        assert CollaborationStatus.completed.value == "completed"
        assert CollaborationStatus.failed.value == "failed"
        assert CollaborationStatus.cancelled.value == "cancelled"


class TestAgentMessageCRUD:
    """Test CRUD operations for agent messages."""
    
    async def test_create_agent_message(self, db_session: AsyncSession):
        """Test creating an agent message."""
        # Create prerequisites
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('msgtest', 'msg@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('MsgAgent') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        # Create message
        message = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-001",
            sender_agent_id=agent_id,
            message_type="request",
            content_json={"action": "search", "query": "test"},
            redaction_level="none",
        )
        
        db_session.add(message)
        await db_session.commit()
        await db_session.refresh(message)
        
        assert message.id is not None
        assert message.collaboration_id == collab.id
        assert message.step_id == "step-001"
        assert message.message_type == "request"
        assert message.content_json == {"action": "search", "query": "test"}
    
    async def test_message_with_null_step_id(self, db_session: AsyncSession):
        """Test creating a message without step_id (nullable)."""
        # Create prerequisites
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('msgtest2', 'msg2@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('MsgAgent2') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        # Create message without step_id
        message = AgentMessage(
            collaboration_id=collab.id,
            step_id=None,
            message_type="notification",
            content_json={"info": "broadcast"},
        )
        
        db_session.add(message)
        await db_session.commit()
        
        assert message.id is not None
        assert message.step_id is None
    
    async def test_message_type_enum_values(self, db_session: AsyncSession):
        """Test that message type enum values are valid."""
        assert MessageType.request.value == "request"
        assert MessageType.response.value == "response"
        assert MessageType.notification.value == "notification"
        assert MessageType.ack.value == "ack"
        assert MessageType.tool_call.value == "tool_call"
        assert MessageType.tool_result.value == "tool_result"
    
    async def test_redaction_level_enum_values(self, db_session: AsyncSession):
        """Test that redaction level enum values are valid."""
        assert MessageRedactionLevel.none.value == "none"
        assert MessageRedactionLevel.partial.value == "partial"
        assert MessageRedactionLevel.full.value == "full"
    
    async def test_message_jsonb_content(self, db_session: AsyncSession):
        """Test that JSONB content can store complex nested structures."""
        # Create prerequisites
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('msgtest3', 'msg3@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('MsgAgent3') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        # Create message with complex JSONB
        complex_content = {
            "action": "tool_execution",
            "tool": "search",
            "parameters": {
                "query": "test",
                "filters": ["tag1", "tag2"],
                "metadata": {"depth": 2, "timeout": 30}
            },
            "results": [
                {"title": "Result 1", "score": 0.95},
                {"title": "Result 2", "score": 0.87}
            ]
        }
        
        message = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-002",
            message_type="tool_result",
            content_json=complex_content,
        )
        
        db_session.add(message)
        await db_session.commit()
        await db_session.refresh(message)
        
        assert message.content_json == complex_content


class TestCascadeDelete:
    """Test CASCADE DELETE behavior for foreign keys."""
    
    async def test_user_delete_cascades_to_collaboration_sessions(self, db_session: AsyncSession):
        """Test that deleting a user cascades to collaboration sessions."""
        # Create user and session
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('cascade_test1', 'cascade1@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('CascadeAgent1') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        collab_id = collab.id
        
        # Delete user
        await db_session.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": user_id}
        )
        await db_session.commit()
        
        # Verify collaboration session was deleted
        result = await db_session.execute(
            select(CollaborationSession).where(CollaborationSession.id == collab_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_collaboration_delete_cascades_to_messages(self, db_session: AsyncSession):
        """Test that deleting a collaboration session cascades to messages."""
        # Create prerequisites
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('cascade_test2', 'cascade2@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('CascadeAgent2') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        # Create messages
        for i in range(3):
            message = AgentMessage(
                collaboration_id=collab.id,
                step_id=f"step-{i}",
                message_type="request",
                content_json={"msg": f"Message {i}"},
            )
            db_session.add(message)
        await db_session.commit()
        
        collab_id = collab.id
        
        # Delete collaboration session
        await db_session.delete(collab)
        await db_session.commit()
        
        # Verify messages were deleted
        result = await db_session.execute(
            select(AgentMessage).where(AgentMessage.collaboration_id == collab_id)
        )
        messages = result.all()
        assert len(messages) == 0
    
    async def test_agent_delete_cascades_to_collaboration_sessions(self, db_session: AsyncSession):
        """Test that deleting an agent instance cascades to collaboration sessions."""
        # Create user and agent
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('cascade_test3', 'cascade3@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('CascadeAgent3') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        collab_id = collab.id
        
        # Delete agent
        await db_session.execute(
            text("DELETE FROM agent_instances WHERE id = :agent_id"),
            {"agent_id": agent_id}
        )
        await db_session.commit()
        
        # Verify collaboration session was deleted
        result = await db_session.execute(
            select(CollaborationSession).where(CollaborationSession.id == collab_id)
        )
        assert result.scalar_one_or_none() is None


class TestSessionMessageRelationship:
    """Test session-message relationship enforcement."""
    
    async def test_step_id_grouping(self, db_session: AsyncSession):
        """Test that messages can be grouped by step_id."""
        # Create prerequisites
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('step_test', 'step@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('StepAgent') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        # Create messages with same step_id (request→response pattern)
        step1_messages = [
            AgentMessage(
                collaboration_id=collab.id,
                step_id="step-001",
                message_type="request",
                content_json={"action": "search"},
            ),
            AgentMessage(
                collaboration_id=collab.id,
                step_id="step-001",
                message_type="response",
                content_json={"results": ["result1", "result2"]},
            ),
        ]
        
        for msg in step1_messages:
            db_session.add(msg)
        
        # Create another step
        step2_message = AgentMessage(
            collaboration_id=collab.id,
            step_id="step-002",
            message_type="tool_call",
            content_json={"tool": "analyzer"},
        )
        db_session.add(step2_message)
        
        await db_session.commit()
        
        # Query by step_id
        result = await db_session.execute(
            select(AgentMessage).where(AgentMessage.step_id == "step-001")
        )
        step1_retrieved = result.all()
        
        assert len(step1_retrieved) == 2
        assert all(msg.step_id == "step-001" for msg, in step1_retrieved)
    
    async def test_messages_ordered_by_created_at(self, db_session: AsyncSession):
        """Test that messages in a session are ordered by created_at."""
        # Create prerequisites
        user_result = await db_session.execute(
            text("INSERT INTO users (username, email) VALUES ('order_test', 'order@example.com') RETURNING id")
        )
        user_id = user_result.scalar_one()
        
        agent_type_result = await db_session.execute(
            text("INSERT INTO agent_types (name) VALUES ('OrderAgent') RETURNING id")
        )
        agent_type_id = agent_type_result.scalar_one()
        
        agent_result = await db_session.execute(
            text("""
                INSERT INTO agent_instances (agent_type_id, user_id, status)
                VALUES (:agent_type_id, :user_id, 'idle')
                RETURNING id
            """),
            {"agent_type_id": agent_type_id, "user_id": user_id}
        )
        agent_id = agent_result.scalar_one()
        
        session_id = f"session-{uuid4()}"
        collab = CollaborationSession(
            user_id=user_id,
            main_agent_id=agent_id,
            session_id=session_id,
        )
        db_session.add(collab)
        await db_session.commit()
        
        # Create messages
        for i in range(5):
            message = AgentMessage(
                collaboration_id=collab.id,
                message_type="request",
                content_json={"index": i},
            )
            db_session.add(message)
            await asyncio.sleep(0.01)  # Small delay for distinct timestamps
        
        await db_session.commit()
        
        # Query messages ordered by created_at
        result = await db_session.execute(
            select(AgentMessage)
            .where(AgentMessage.collaboration_id == collab.id)
            .order_by(AgentMessage.created_at)
        )
        messages = result.scalars().all()
        
        assert len(messages) == 5
        # Verify ordering by checking content
        for i in range(len(messages) - 1):
            assert messages[i].created_at <= messages[i + 1].created_at


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_collaboration_session_create_validation(self):
        """Test CollaborationSessionCreate validation."""
        from db.models.collaboration import CollaborationSessionCreate
        
        user_id = uuid4()
        agent_id = uuid4()
        session_id = f"session-{uuid4()}"
        
        data = {
            "user_id": user_id,
            "main_agent_id": agent_id,
            "session_id": session_id,
            "name": "Test Session",
            "status": "active",
            "involves_secrets": False,
            "context_json": {"key": "value"},
        }
        
        model = CollaborationSessionCreate(**data)
        assert model.user_id == user_id
        assert model.main_agent_id == agent_id
        assert model.session_id == session_id
        assert model.name == "Test Session"
    
    def test_agent_message_create_validation(self):
        """Test AgentMessageCreate validation."""
        from db.models.collaboration import AgentMessageCreate
        
        collab_id = uuid4()
        sender_id = uuid4()
        
        data = {
            "collaboration_id": collab_id,
            "sender_agent_id": sender_id,
            "message_type": "request",
            "content_json": {"action": "test"},
            "redaction_level": "none",
        }
        
        model = AgentMessageCreate(**data)
        assert model.collaboration_id == collab_id
        assert model.sender_agent_id == sender_id
        assert model.message_type == "request"
        assert model.content_json == {"action": "test"}
    
    def test_enum_coercion_in_pydantic(self):
        """Test that string values are coerced to enums in Pydantic models."""
        from db.models.collaboration import CollaborationSessionCreate, AgentMessageCreate
        
        user_id = uuid4()
        agent_id = uuid4()
        collab_id = uuid4()
        
        # Test CollaborationSessionCreate with string status
        collab_data = {
            "user_id": user_id,
            "main_agent_id": agent_id,
            "session_id": f"session-{uuid4()}",
            "status": "completed",  # String, not enum
        }
        collab_model = CollaborationSessionCreate(**collab_data)
        assert collab_model.status == "completed"
        
        # Test AgentMessageCreate with string message_type
        message_data = {
            "collaboration_id": collab_id,
            "message_type": "tool_call",  # String, not enum
            "content_json": {},
            "redaction_level": "partial",  # String, not enum
        }
        message_model = AgentMessageCreate(**message_data)
        assert message_model.message_type == "tool_call"
        assert message_model.redaction_level == "partial"
