# pyright: reportMissingImports=false
"""
Tests for agent database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and JSONB validation for agent_types
and agent_instances tables.
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
from db.entity.agent_entity import AgentType, AgentInstance
from db.entity.llm_endpoint_entity import LLMEndpointGroup  # noqa: F401 - Import for relationship resolution
from db.types import AgentStatus, gen_random_uuid


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
        
        # Create indexes
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
        
        # Create tasks table (needed for User relationship)
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
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestAgentTypeSchema:
    """Test agent_types schema creation and structure."""
    
    async def test_agent_types_table_exists(self, db_session: AsyncSession):
        """Test that the agent_types table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'agent_types'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "agent_types"
    
    async def test_agent_types_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in agent_types table."""
        expected_columns = {
            'id', 'name', 'description', 'capabilities', 'default_config',
            'is_active', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agent_types'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_agent_types_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'agent_types'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_agent_types_name' in indexes
        assert 'idx_agent_types_is_active' in indexes
    
    async def test_unique_constraint_on_name(self, db_session: AsyncSession):
        """Test that name has a unique constraint."""
        # Insert first agent type
        await db_session.execute(text("""
            INSERT INTO agent_types (name, description) 
            VALUES ('TestAgent', 'First test agent')
        """))
        await db_session.commit()
        
        # Try to insert duplicate name - should fail
        with pytest.raises(IntegrityError):
            await db_session.execute(text("""
                INSERT INTO agent_types (name, description) 
                VALUES ('TestAgent', 'Duplicate test agent')
            """))
            await db_session.commit()


class TestAgentInstanceSchema:
    """Test agent_instances schema creation and structure."""
    
    async def test_agent_instances_table_exists(self, db_session: AsyncSession):
        """Test that the agent_instances table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'agent_instances'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "agent_instances"
    
    async def test_agent_instances_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in agent_instances table."""
        expected_columns = {
            'id', 'agent_type_id', 'user_id', 'name', 'status', 'config',
            'last_heartbeat_at', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agent_instances'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_agent_instances_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'agent_instances'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_agent_instances_status' in indexes
        assert 'idx_agent_instances_user' in indexes
    
    async def test_check_constraint_on_status(self, db_session: AsyncSession):
        """Test that status has a check constraint."""
        # Insert valid status - should succeed
        await db_session.execute(text("""
            INSERT INTO users (id, username, email) 
            VALUES (gen_random_uuid(), 'testuser', 'test@example.com')
        """))
        await db_session.execute(text("""
            INSERT INTO agent_types (id, name) 
            VALUES (gen_random_uuid(), 'TestAgent')
        """))
        await db_session.commit()
        
        # Get IDs for FK
        user_result = await db_session.execute(
            text("SELECT id FROM users WHERE username = 'testuser'")
        )
        user_id = user_result.scalar_one()
        
        type_result = await db_session.execute(
            text("SELECT id FROM agent_types WHERE name = 'TestAgent'")
        )
        type_id = type_result.scalar_one()
        
        # Valid status should work
        await db_session.execute(text(f"""
            INSERT INTO agent_instances (agent_type_id, user_id, status) 
            VALUES ('{type_id}', '{user_id}', 'idle')
        """))
        await db_session.commit()
        
        # Invalid status should fail
        with pytest.raises(IntegrityError):
            await db_session.execute(text(f"""
                INSERT INTO agent_instances (agent_type_id, user_id, status) 
                VALUES ('{type_id}', '{user_id}', 'invalid_status')
            """))
            await db_session.commit()


class TestAgentTypeCRUD:
    """Test CRUD operations for AgentType model."""
    
    async def test_create_agent_type_minimal(self, db_session: AsyncSession):
        """Test creating an agent type with minimal fields."""
        agent_type = AgentType(
            name="MinimalAgent",
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        assert agent_type.id is not None
        assert isinstance(agent_type.id, UUID)
        assert agent_type.name == "MinimalAgent"
        assert agent_type.description is None
        assert agent_type.capabilities is None
        assert agent_type.default_config is None
        assert agent_type.is_active is True
        assert agent_type.created_at is not None
        assert agent_type.updated_at is not None
    
    async def test_create_agent_type_full(self, db_session: AsyncSession):
        """Test creating an agent type with all fields."""
        capabilities = {
            "web_search": True,
            "summarization": True,
            "max_tokens": 4096,
        }
        default_config = {
            "temperature": 0.7,
            "max_results": 10,
            "timeout_seconds": 30,
        }
        
        agent_type = AgentType(
            name="ResearchAgent",
            description="An agent that performs web research",
            capabilities=capabilities,
            default_config=default_config,
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        assert agent_type.name == "ResearchAgent"
        assert agent_type.description == "An agent that performs web research"
        assert isinstance(agent_type.capabilities, dict)
        assert agent_type.capabilities["web_search"] is True
        assert agent_type.capabilities["max_tokens"] == 4096
        assert isinstance(agent_type.default_config, dict)
        assert agent_type.default_config["temperature"] == 0.7
        assert agent_type.is_active is True
    
    async def test_update_agent_type(self, db_session: AsyncSession):
        """Test updating an agent type."""
        agent_type = AgentType(name="UpdateTest")
        db_session.add(agent_type)
        await db_session.commit()
        
        original_updated_at = agent_type.updated_at
        await asyncio.sleep(0.01)  # Ensure time difference
        
        agent_type.description = "Updated description"
        agent_type.is_active = False
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        assert agent_type.description == "Updated description"
        assert agent_type.is_active is False
        assert agent_type.updated_at > original_updated_at
    
    async def test_delete_agent_type(self, db_session: AsyncSession):
        """Test deleting an agent type."""
        agent_type = AgentType(name="DeleteTest")
        db_session.add(agent_type)
        await db_session.commit()
        
        await db_session.delete(agent_type)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AgentType).where(AgentType.id == agent_type.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_get_agent_type_by_id(self, db_session: AsyncSession):
        """Test retrieving an agent type by ID."""
        agent_type = AgentType(name="GetTest", description="Test for retrieval")
        db_session.add(agent_type)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AgentType).where(AgentType.id == agent_type.id)
        )
        fetched = result.scalar_one()
        
        assert fetched is not None
        assert fetched.id == agent_type.id
        assert fetched.name == "GetTest"
        assert fetched.description == "Test for retrieval"
    
    async def test_list_active_agent_types(self, db_session: AsyncSession):
        """Test listing only active agent types."""
        # Create mixed active/inactive types
        for i, active in enumerate([True, False, True, True, False]):
            agent_type = AgentType(
                name=f"Agent{i}",
                is_active=active,
            )
            db_session.add(agent_type)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AgentType).where(AgentType.is_active is True)
        )
        active_types = result.scalars().all()
        
        assert len(active_types) == 3
        assert all(t.is_active for t in active_types)


class TestAgentInstanceCRUD:
    """Test CRUD operations for AgentInstance model."""
    
    async def test_create_agent_instance_minimal(self, db_session: AsyncSession):
        """Test creating an agent instance with minimal fields."""
        # Create user and agent type first
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        instance = AgentInstance(
            agent_type_id=agent_type_id,
            user_id=user_id,
        )
        db_session.add(instance)
        await db_session.commit()
        await db_session.refresh(instance)
        
        assert instance.id is not None
        assert isinstance(instance.id, UUID)
        assert instance.agent_type_id == agent_type_id
        assert instance.user_id == user_id
        assert instance.status == AgentStatus.idle
        assert instance.config is None
        assert instance.name is None
    
    async def test_create_agent_instance_full(self, db_session: AsyncSession):
        """Test creating an agent instance with all fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        config = {
            "temperature": 0.8,
            "max_iterations": 5,
            "custom_param": "value",
        }
        
        instance = AgentInstance(
            agent_type_id=agent_type_id,
            user_id=user_id,
            name="MyAgent-001",
            status=AgentStatus.busy,
            config=config,
        )
        db_session.add(instance)
        await db_session.commit()
        await db_session.refresh(instance)
        
        assert instance.name == "MyAgent-001"
        assert instance.status == AgentStatus.busy
        assert isinstance(instance.config, dict)
        assert instance.config["temperature"] == 0.8
    
    async def test_update_agent_instance_status(self, db_session: AsyncSession):
        """Test updating agent instance status."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        instance = AgentInstance(
            agent_type_id=agent_type_id,
            user_id=user_id,
            status=AgentStatus.idle,
        )
        db_session.add(instance)
        await db_session.commit()
        
        original_updated_at = instance.updated_at
        await asyncio.sleep(0.01)
        
        instance.status = AgentStatus.error
        await db_session.commit()
        await db_session.refresh(instance)
        
        assert instance.status == AgentStatus.error
        assert instance.updated_at > original_updated_at
    
    async def test_update_heartbeat(self, db_session: AsyncSession):
        """Test updating last_heartbeat_at."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        instance = AgentInstance(
            agent_type_id=agent_type_id,
            user_id=user_id,
        )
        db_session.add(instance)
        await db_session.commit()
        
        now = datetime.now(timezone.utc)
        instance.last_heartbeat_at = now
        await db_session.commit()
        await db_session.refresh(instance)
        
        assert instance.last_heartbeat_at is not None
        # Compare timestamps (allow small difference)
        assert abs((instance.last_heartbeat_at - now).total_seconds()) < 1


class TestForeignKeys:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_agent_type_id_enforced(self, db_session: AsyncSession):
        """Test that agent_type_id FK constraint is enforced."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Try to create instance with non-existent agent_type_id
        fake_type_id = uuid4()
        instance = AgentInstance(
            agent_type_id=fake_type_id,
            user_id=user_id,
        )
        db_session.add(instance)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_fk_user_id_enforced(self, db_session: AsyncSession):
        """Test that user_id FK constraint is enforced."""
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        # Try to create instance with non-existent user_id
        fake_user_id = uuid4()
        instance = AgentInstance(
            agent_type_id=agent_type_id,
            user_id=fake_user_id,
        )
        db_session.add(instance)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_agent_type(self, db_session: AsyncSession):
        """Test that deleting agent type cascades to instances."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        # Create instances
        for i in range(3):
            instance = AgentInstance(
                agent_type_id=agent_type_id,
                user_id=user_id,
                name=f"Instance{i}",
            )
            db_session.add(instance)
        await db_session.commit()
        
        # Delete agent type
        await db_session.execute(text(f"""
            DELETE FROM agent_types WHERE id = '{agent_type_id}'
        """))
        await db_session.commit()
        
        # Verify instances are deleted
        result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_type_id == agent_type_id)
        )
        instances = result.scalars().all()
        assert len(instances) == 0
    
    async def test_cascade_delete_user(self, db_session: AsyncSession):
        """Test that deleting user cascades to agent instances."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        # Create instances for this user
        for i in range(2):
            instance = AgentInstance(
                agent_type_id=agent_type_id,
                user_id=user_id,
                name=f"Instance{i}",
            )
            db_session.add(instance)
        await db_session.commit()
        
        # Delete user
        await db_session.execute(text(f"""
            DELETE FROM users WHERE id = '{user_id}'
        """))
        await db_session.commit()
        
        # Verify instances are deleted
        result = await db_session.execute(
            select(AgentInstance).where(AgentInstance.user_id == user_id)
        )
        instances = result.scalars().all()
        assert len(instances) == 0


class TestAgentStatusEnum:
    """Test AgentStatus enum usage."""
    
    async def test_all_enum_values_valid(self, db_session: AsyncSession):
        """Test that all AgentStatus enum values are valid."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        # Test each enum value
        for status in AgentStatus:
            instance = AgentInstance(
                agent_type_id=agent_type_id,
                user_id=user_id,
                status=status,
                name=f"Test_{status.value}",
            )
            db_session.add(instance)
            await db_session.commit()
            await db_session.refresh(instance)
            
            assert instance.status == status
            await db_session.delete(instance)
            await db_session.commit()
    
    async def test_enum_serialization(self, db_session: AsyncSession):
        """Test that AgentStatus serializes correctly."""
        assert str(AgentStatus.idle) == "idle"
        assert AgentStatus.idle.value == "idle"
        assert not isinstance(AgentStatus.idle.value, int)
        
        assert str(AgentStatus.busy) == "busy"
        assert str(AgentStatus.error) == "error"
        assert str(AgentStatus.offline) == "offline"


class TestJSONBValidation:
    """Test JSONB field validation for capabilities and config."""
    
    async def test_capabilities_accepts_dict(self, db_session: AsyncSession):
        """Test that capabilities accepts dictionary."""
        agent_type = AgentType(
            name="JSONTest",
            capabilities={"key": "value", "nested": {"inner": True}},
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        assert isinstance(agent_type.capabilities, dict)
        assert agent_type.capabilities["key"] == "value"
        assert agent_type.capabilities["nested"]["inner"] is True
    
    async def test_capabilities_accepts_list(self, db_session: AsyncSession):
        """Test that capabilities accepts list."""
        agent_type = AgentType(
            name="ListTest",
            capabilities={"features": ["search", "summarize", "analyze"]},
        )
        db_session.add(agent_type)
        await db_session.commit()
        await db_session.refresh(agent_type)
        
        assert isinstance(agent_type.capabilities, dict)
        assert agent_type.capabilities["features"] == ["search", "summarize", "analyze"]
    
    async def test_config_accepts_complex_structure(self, db_session: AsyncSession):
        """Test that config accepts complex nested structures."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        agent_type_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        complex_config = {
            "llm": {
                "model": "gpt-4",
                "temperature": 0.7,
                "max_tokens": 4096,
            },
            "tools": [
                {"name": "search", "enabled": True},
                {"name": "calculator", "enabled": False},
            ],
            "retries": {
                "max_attempts": 3,
                "backoff": {
                    "type": "exponential",
                    "base": 2,
                    "max_delay": 60,
                },
            },
        }
        
        instance = AgentInstance(
            agent_type_id=agent_type_id,
            user_id=user_id,
            config=complex_config,
        )
        db_session.add(instance)
        await db_session.commit()
        await db_session.refresh(instance)
        
        assert isinstance(instance.config, dict)
        assert instance.config["llm"]["model"] == "gpt-4"
        assert len(instance.config["tools"]) == 2
        assert instance.config["retries"]["backoff"]["base"] == 2


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_agent_type_create_validation(self):
        """Test AgentTypeCreate model validation."""
        from db.models.agent import AgentTypeCreate
        
        # Valid creation
        data = {
            "name": "ValidAgent",
            "description": "A valid test agent",
            "capabilities": {"feature1": True},
            "default_config": {"param": "value"},
        }
        model = AgentTypeCreate(**data)
        
        assert model.name == "ValidAgent"
        assert model.description == "A valid test agent"
        assert model.capabilities == {"feature1": True}
    
    def test_agent_instance_create_validation(self):
        """Test AgentInstanceCreate model validation."""
        from db.models.agent import AgentInstanceCreate
        
        user_id = gen_random_uuid()
        type_id = gen_random_uuid()
        
        data = {
            "agent_type_id": type_id,
            "user_id": user_id,
            "name": "TestInstance",
            "status": AgentStatus.idle,
            "config": {"custom": "config"},
        }
        model = AgentInstanceCreate(**data)
        
        assert model.agent_type_id == type_id
        assert model.user_id == user_id
        assert model.name == "TestInstance"
        assert model.status == AgentStatus.idle
    
    def test_agent_status_string_coercion(self):
        """Test that string values are coerced to AgentStatus enum."""
        from db.models.agent import AgentInstanceCreate
        
        user_id = gen_random_uuid()
        type_id = gen_random_uuid()
        
        # Pass status as string - should be coerced
        data = {
            "agent_type_id": type_id,
            "user_id": user_id,
            "status": "busy",  # String, not enum
        }
        model = AgentInstanceCreate(**data)
        
        assert model.status == AgentStatus.busy
        assert isinstance(model.status, AgentStatus)
