# pyright: reportMissingImports=false
"""
Tests for agent capability database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and JSONB validation for agent_capabilities table.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Dict
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.schema.agent_capabilities import AgentCapability
from db.schema.agents import AgentType  # noqa: F401 - Import for FK relationship


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
        
        # Create agent_capabilities table
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
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capabilities_type 
            ON agent_capabilities(agent_type_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capabilities_name 
            ON agent_capabilities(capability_name)
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS agent_capabilities"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestAgentCapabilitySchema:
    """Test agent_capabilities schema creation and structure."""
    
    async def test_agent_capabilities_table_exists(self, db_session: AsyncSession):
        """Test that the agent_capabilities table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'agent_capabilities'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "agent_capabilities"
    
    async def test_agent_capabilities_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in agent_capabilities table."""
        expected_columns = {
            'id', 'agent_type_id', 'capability_name', 'description',
            'input_schema', 'output_schema', 'is_active', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agent_capabilities'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_agent_capabilities_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'agent_capabilities'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_capabilities_type' in indexes
        assert 'idx_capabilities_name' in indexes


class TestAgentCapabilityCRUD:
    """Test CRUD operations for AgentCapability model."""
    
    async def test_create_capability_minimal(self, db_session: AsyncSession):
        """Test creating a capability with minimal fields."""
        # Create agent type first
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="minimal_capability",
        )
        db_session.add(capability)
        await db_session.commit()
        await db_session.refresh(capability)
        
        assert capability.id is not None
        assert isinstance(capability.id, UUID)
        assert capability.agent_type_id == agent_type_id
        assert capability.capability_name == "minimal_capability"
        assert capability.description is None
        assert capability.input_schema is None
        assert capability.output_schema is None
        assert capability.is_active is True
        assert capability.created_at is not None
        assert capability.updated_at is not None
    
    async def test_create_capability_full(self, db_session: AsyncSession):
        """Test creating a capability with all fields."""
        # Create agent type first
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10}
            },
            "required": ["query"]
        }
        
        output_schema = {
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "object"}}
            }
        }
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="web_search",
            description="Search the web for information",
            input_schema=input_schema,
            output_schema=output_schema,
            is_active=True,
        )
        db_session.add(capability)
        await db_session.commit()
        await db_session.refresh(capability)
        
        assert capability.capability_name == "web_search"
        assert capability.description == "Search the web for information"
        assert isinstance(capability.input_schema, dict)
        assert capability.input_schema["type"] == "object"
        assert "query" in capability.input_schema["properties"]
        assert isinstance(capability.output_schema, dict)
        assert capability.output_schema["properties"]["results"]["type"] == "array"
        assert capability.is_active is True
    
    async def test_update_capability(self, db_session: AsyncSession):
        """Test updating a capability."""
        # Create agent type first
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="UpdateTest",
        )
        db_session.add(capability)
        await db_session.commit()
        
        original_updated_at = capability.updated_at
        await asyncio.sleep(0.01)  # Ensure time difference
        
        capability.description = "Updated description"
        capability.is_active = False
        await db_session.commit()
        await db_session.refresh(capability)
        
        assert capability.description == "Updated description"
        assert capability.is_active is False
        assert capability.updated_at > original_updated_at
    
    async def test_delete_capability(self, db_session: AsyncSession):
        """Test deleting a capability."""
        # Create agent type first
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="DeleteTest",
        )
        db_session.add(capability)
        await db_session.commit()
        
        await db_session.delete(capability)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.id == capability.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_get_capability_by_id(self, db_session: AsyncSession):
        """Test retrieving a capability by ID."""
        # Create agent type first
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="GetTest",
            description="Test for retrieval",
        )
        db_session.add(capability)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.id == capability.id)
        )
        fetched = result.scalar_one()
        
        assert fetched is not None
        assert fetched.id == capability.id
        assert fetched.capability_name == "GetTest"
        assert fetched.description == "Test for retrieval"
    
    async def test_list_active_capabilities(self, db_session: AsyncSession):
        """Test listing only active capabilities."""
        # Create agent type first
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        # Create mixed active/inactive capabilities
        for i, active in enumerate([True, False, True, True, False]):
            capability = AgentCapability(
                agent_type_id=agent_type_id,
                capability_name=f"Capability{i}",
                is_active=active,
            )
            db_session.add(capability)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.is_active is True)
        )
        active_capabilities = result.scalars().all()
        
        assert len(active_capabilities) == 3
        assert all(c.is_active for c in active_capabilities)


class TestForeignKeyConstraints:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_agent_type_id_enforced(self, db_session: AsyncSession):
        """Test that agent_type_id FK constraint is enforced."""
        # Try to create capability with non-existent agent_type_id
        fake_type_id = uuid4()
        capability = AgentCapability(
            agent_type_id=fake_type_id,
            capability_name="InvalidCapability",
        )
        db_session.add(capability)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_agent_type(self, db_session: AsyncSession):
        """Test that deleting agent type cascades to capabilities."""
        # Create agent type
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        # Create capabilities
        for i in range(3):
            capability = AgentCapability(
                agent_type_id=agent_type_id,
                capability_name=f"Capability{i}",
            )
            db_session.add(capability)
        await db_session.commit()
        
        # Delete agent type
        await db_session.execute(text(f"""
            DELETE FROM agent_types WHERE id = '{agent_type_id}'
        """))
        await db_session.commit()
        
        # Verify capabilities are deleted
        result = await db_session.execute(
            select(AgentCapability).where(AgentCapability.agent_type_id == agent_type_id)
        )
        capabilities = result.scalars().all()
        assert len(capabilities) == 0


class TestJSONBValidation:
    """Test JSONB field validation for input_schema and output_schema."""
    
    async def test_input_schema_accepts_dict(self, db_session: AsyncSession):
        """Test that input_schema accepts dictionary."""
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="JSONTest",
            input_schema={"key": "value", "nested": {"inner": True}},
        )
        db_session.add(capability)
        await db_session.commit()
        await db_session.refresh(capability)
        
        assert isinstance(capability.input_schema, dict)
        assert capability.input_schema["key"] == "value"
        assert capability.input_schema["nested"]["inner"] is True
    
    async def test_input_schema_accepts_list(self, db_session: AsyncSession):
        """Test that input_schema accepts list."""
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="ListTest",
            input_schema={"features": ["search", "summarize", "analyze"]},
        )
        db_session.add(capability)
        await db_session.commit()
        await db_session.refresh(capability)
        
        assert isinstance(capability.input_schema, dict)
        assert capability.input_schema["features"] == ["search", "summarize", "analyze"]
    
    async def test_output_schema_accepts_complex_structure(self, db_session: AsyncSession):
        """Test that output_schema accepts complex nested structures."""
        agent_type_id = uuid4()
        await db_session.execute(text(f"""
            INSERT INTO agent_types (id, name) 
            VALUES ('{agent_type_id}', 'TestAgent')
        """))
        await db_session.commit()
        
        complex_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "name": {"type": "string"}
                                }
                            }
                        }
                    }
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "total": {"type": "integer"},
                        "page": {"type": "integer"}
                    }
                }
            }
        }
        
        capability = AgentCapability(
            agent_type_id=agent_type_id,
            capability_name="ComplexSchema",
            output_schema=complex_schema,
        )
        db_session.add(capability)
        await db_session.commit()
        await db_session.refresh(capability)
        
        assert isinstance(capability.output_schema, dict)
        assert capability.output_schema["type"] == "object"
        assert "data" in capability.output_schema["properties"]
        assert capability.output_schema["properties"]["data"]["properties"]["items"]["type"] == "array"


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_capability_create_validation(self):
        """Test AgentCapabilityCreate model validation."""
        from db.models.capability import AgentCapabilityCreate
        
        type_id = uuid4()
        
        # Valid creation
        data = {
            "agent_type_id": type_id,
            "capability_name": "ValidCapability",
            "description": "A valid test capability",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "is_active": True,
        }
        model = AgentCapabilityCreate(**data)
        
        assert model.agent_type_id == type_id
        assert model.capability_name == "ValidCapability"
        assert model.description == "A valid test capability"
        assert model.input_schema == {"type": "object"}
        assert model.output_schema == {"type": "object"}
        assert model.is_active is True
    
    def test_capability_minimal_validation(self):
        """Test minimal capability creation."""
        from db.models.capability import AgentCapabilityCreate
        
        type_id = uuid4()
        
        data = {
            "agent_type_id": type_id,
            "capability_name": "MinimalCapability",
        }
        model = AgentCapabilityCreate(**data)
        
        assert model.agent_type_id == type_id
        assert model.capability_name == "MinimalCapability"
        assert model.description is None
        assert model.input_schema is None
        assert model.output_schema is None
        assert model.is_active is True
    
    def test_capability_full_model(self):
        """Test full AgentCapability model."""
        from db.models.capability import AgentCapability
        
        type_id = uuid4()
        cap_id = uuid4()
        
        data = {
            "id": cap_id,
            "agent_type_id": type_id,
            "capability_name": "FullCapability",
            "description": "Full test capability",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"result": {"type": "string"}}},
            "is_active": True,
            "created_at": "2026-03-22T12:00:00Z",
            "updated_at": "2026-03-22T12:00:00Z",
        }
        model = AgentCapability(**data)
        
        assert model.id == cap_id
        assert model.agent_type_id == type_id
        assert model.capability_name == "FullCapability"
        assert model.description == "Full test capability"
        assert model.input_schema["type"] == "object"
        assert model.output_schema["properties"]["result"]["type"] == "string"
