# pyright: reportMissingImports=false
"""
Tests for AgentCapabilityDAO database operations.

This module tests CRUD operations for AgentCapabilityDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.agent_capability_dto import (
    AgentCapabilityCreate,
    AgentCapability,
    AgentCapabilityUpdate,
)
from db.dto.agent_dto import AgentTypeCreate
from db.dao.agent_capability_dao import AgentCapabilityDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.entity.agent_capability_entity import AgentCapability as AgentCapabilityEntity
from db.entity.agent_entity import AgentType as AgentTypeEntity


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
async def clean_tables(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean agent_capabilities and agent_types tables before and after tests."""
    await db_session.execute(delete(AgentCapabilityEntity))
    await db_session.execute(delete(AgentTypeEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(AgentCapabilityEntity))
    await db_session.execute(delete(AgentTypeEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_agent_type(db_session: AsyncSession, clean_tables: None) -> AgentType:
    """Create a test agent type for capability tests."""
    agent_type_create = AgentTypeCreate(
        name="TestAgentType",
        description="Test agent type for capability tests",
    )
    return await AgentTypeDAO.create(agent_type_create, session=db_session)


class TestAgentCapabilityDAOCreate:
    """Test create operations for AgentCapabilityDAO."""
    
    async def test_create_capability_with_minimal_fields(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test creating a capability with only required fields."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="web_search",
        )
        
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        assert created is not None
        assert created.id is not None
        assert isinstance(created.id, UUID)
        assert created.agent_type_id == test_agent_type.id
        assert created.capability_name == "web_search"
        assert created.description is None
        assert created.input_schema is None
        assert created.output_schema is None
        assert created.is_active is True  # Default value
        assert created.created_at is not None
        assert created.updated_at is not None
        assert isinstance(created.created_at, datetime)
        assert isinstance(created.updated_at, datetime)
    
    async def test_create_capability_with_all_fields(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test creating a capability with all fields specified."""
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
        
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="full_capability",
            description="A fully configured capability",
            input_schema=input_schema,
            output_schema=output_schema,
            is_active=False,
        )
        
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        assert created is not None
        assert created.agent_type_id == test_agent_type.id
        assert created.capability_name == "full_capability"
        assert created.description == "A fully configured capability"
        assert created.input_schema == input_schema
        assert created.output_schema == output_schema
        assert created.is_active is False
    
    async def test_create_capability_returns_dto(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that create returns an AgentCapability DTO, not an entity."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="dto_test",
        )
        
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        assert isinstance(created, AgentCapability)
    
    async def test_create_capability_with_invalid_agent_type_raises_error(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that creating a capability with invalid agent_type_id raises IntegrityError."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=uuid4(),  # Non-existent agent type
            capability_name="invalid_test",
        )
        
        with pytest.raises(Exception):  # IntegrityError
            await AgentCapabilityDAO.create(capability_create, session=db_session)


class TestAgentCapabilityDAOGetById:
    """Test get_by_id operations for AgentCapabilityDAO."""
    
    async def test_get_by_id_returns_capability(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test retrieving a capability by ID."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="get_test",
            description="Test retrieval",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.capability_name == "get_test"
        assert fetched.description == "Test retrieval"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        result = await AgentCapabilityDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that get_by_id returns an AgentCapability DTO."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="dto_get_test",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, AgentCapability)


class TestAgentCapabilityDAOGetByAgentTypeId:
    """Test get_by_agent_type_id operations for AgentCapabilityDAO."""
    
    async def test_get_by_agent_type_id_returns_capabilities(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test retrieving capabilities by agent_type_id."""
        for i in range(3):
            capability_create = AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name=f"cap_{i}",
            )
            await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        capabilities = await AgentCapabilityDAO.get_by_agent_type_id(
            test_agent_type.id, session=db_session
        )
        
        assert len(capabilities) == 3
        names = {c.capability_name for c in capabilities}
        assert names == {"cap_0", "cap_1", "cap_2"}
    
    async def test_get_by_agent_type_id_empty_returns_empty_list(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that get_by_agent_type_id returns empty list when no capabilities exist."""
        capabilities = await AgentCapabilityDAO.get_by_agent_type_id(
            test_agent_type.id, session=db_session
        )
        
        assert capabilities == []
    
    async def test_get_by_agent_type_id_with_pagination(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test get_by_agent_type_id with limit and offset."""
        for i in range(5):
            capability_create = AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name=f"page_cap_{i}",
            )
            await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        # Test limit
        capabilities_limited = await AgentCapabilityDAO.get_by_agent_type_id(
            test_agent_type.id, limit=2, session=db_session
        )
        assert len(capabilities_limited) == 2
        
        # Test offset
        capabilities_offset = await AgentCapabilityDAO.get_by_agent_type_id(
            test_agent_type.id, limit=2, offset=2, session=db_session
        )
        assert len(capabilities_offset) == 2


class TestAgentCapabilityDAOGetAll:
    """Test get_all operations for AgentCapabilityDAO."""
    
    async def test_get_all_returns_all_capabilities(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test retrieving all capabilities."""
        for i in range(3):
            capability_create = AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name=f"all_cap_{i}",
            )
            await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        capabilities = await AgentCapabilityDAO.get_all(session=db_session)
        
        assert len(capabilities) == 3
        names = {c.capability_name for c in capabilities}
        assert names == {"all_cap_0", "all_cap_1", "all_cap_2"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_all returns empty list when no capabilities exist."""
        capabilities = await AgentCapabilityDAO.get_all(session=db_session)
        
        assert capabilities == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            capability_create = AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name=f"page_all_cap_{i}",
            )
            await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        # Test limit
        capabilities_limited = await AgentCapabilityDAO.get_all(limit=2, session=db_session)
        assert len(capabilities_limited) == 2
        
        # Test offset
        capabilities_offset = await AgentCapabilityDAO.get_all(
            limit=2, offset=2, session=db_session
        )
        assert len(capabilities_offset) == 2
        
        # Verify different capabilities returned
        ids_limited = {c.id for c in capabilities_limited}
        ids_offset = {c.id for c in capabilities_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that get_all returns AgentCapability DTOs."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="dto_list_test",
        )
        await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        capabilities = await AgentCapabilityDAO.get_all(session=db_session)
        
        assert len(capabilities) == 1
        assert isinstance(capabilities[0], AgentCapability)
    
    async def test_get_all_active_only(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test get_all with active_only filter."""
        # Create active and inactive capabilities
        await AgentCapabilityDAO.create(
            AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name="active_cap",
                is_active=True,
            ),
            session=db_session
        )
        await AgentCapabilityDAO.create(
            AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name="inactive_cap",
                is_active=False,
            ),
            session=db_session
        )
        
        active_caps = await AgentCapabilityDAO.get_all(active_only=True, session=db_session)
        
        assert len(active_caps) == 1
        assert active_caps[0].capability_name == "active_cap"


class TestAgentCapabilityDAOUpdate:
    """Test update operations for AgentCapabilityDAO."""
    
    async def test_update_capability_description(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test updating a capability's description."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="update_test",
            description="Before update",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        # Wait a tiny bit to ensure timestamp changes
        await asyncio.sleep(0.01)
        
        capability_update = AgentCapabilityUpdate(
            id=created.id,
            description="After update",
        )
        updated = await AgentCapabilityDAO.update(capability_update, session=db_session)
        
        assert updated is not None
        assert updated.capability_name == "update_test"
        assert updated.description == "After update"
        assert updated.updated_at > created.updated_at
    
    async def test_update_capability_is_active(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test updating a capability's is_active status."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="active_update_test",
            is_active=True,
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        capability_update = AgentCapabilityUpdate(
            id=created.id,
            is_active=False,
        )
        updated = await AgentCapabilityDAO.update(capability_update, session=db_session)
        
        assert updated is not None
        assert updated.is_active is False
    
    async def test_update_capability_schemas(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test updating a capability's input/output schemas."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="schema_update_test",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        new_input_schema = {"type": "string"}
        new_output_schema = {"type": "number"}
        
        capability_update = AgentCapabilityUpdate(
            id=created.id,
            input_schema=new_input_schema,
            output_schema=new_output_schema,
        )
        updated = await AgentCapabilityDAO.update(capability_update, session=db_session)
        
        assert updated is not None
        assert updated.input_schema == new_input_schema
        assert updated.output_schema == new_output_schema
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that updating a nonexistent capability returns None."""
        capability_update = AgentCapabilityUpdate(
            id=uuid4(),
            description="Nonexistent",
        )
        
        result = await AgentCapabilityDAO.update(capability_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that update returns an AgentCapability DTO."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="dto_update_test",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        capability_update = AgentCapabilityUpdate(
            id=created.id,
            description="Updated",
        )
        updated = await AgentCapabilityDAO.update(capability_update, session=db_session)
        
        assert isinstance(updated, AgentCapability)


class TestAgentCapabilityDAODelete:
    """Test delete operations for AgentCapabilityDAO."""
    
    async def test_delete_existing_capability(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test deleting an existing capability."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="delete_test",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        result = await AgentCapabilityDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify capability is deleted
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that deleting a nonexistent capability returns False."""
        result = await AgentCapabilityDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestAgentCapabilityDAOExists:
    """Test exists operations for AgentCapabilityDAO."""
    
    async def test_exists_returns_true_for_existing(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that exists returns True for existing capability."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="exists_test",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        result = await AgentCapabilityDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that exists returns False for nonexistent capability."""
        result = await AgentCapabilityDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestAgentCapabilityDAOCount:
    """Test count operations for AgentCapabilityDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that count returns the correct number of capabilities."""
        for i in range(3):
            capability_create = AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name=f"count_cap_{i}",
            )
            await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        count = await AgentCapabilityDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that count returns 0 for empty table."""
        count = await AgentCapabilityDAO.count(session=db_session)
        
        assert count == 0


class TestAgentCapabilityDAOJSONBFields:
    """Test JSONB field handling for AgentCapabilityDAO."""
    
    async def test_input_schema_jsonb_persistence(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that input_schema JSONB field persists correctly."""
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10}
            },
            "required": ["query"],
            "nested": {"deep": {"key": "value"}},
        }
        
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="jsonb_input_test",
            input_schema=input_schema,
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.input_schema == input_schema
    
    async def test_output_schema_jsonb_persistence(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that output_schema JSONB field persists correctly."""
        output_schema = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                        }
                    }
                }
            },
        }
        
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="jsonb_output_test",
            output_schema=output_schema,
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.output_schema == output_schema
    
    async def test_both_schemas_jsonb_persistence(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that both input and output schemas persist correctly."""
        input_schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
        output_schema = {
            "type": "object",
            "properties": {"sentiment": {"type": "string"}},
        }
        
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="jsonb_both_test",
            input_schema=input_schema,
            output_schema=output_schema,
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.input_schema == input_schema
        assert fetched.output_schema == output_schema


class TestAgentCapabilityDAOForeignKeyRelationship:
    """Test foreign key relationship with agent_types."""
    
    async def test_capabilities_deleted_on_agent_type_cascade(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that capabilities are deleted when agent type is deleted (CASCADE)."""
        capability_create = AgentCapabilityCreate(
            agent_type_id=test_agent_type.id,
            capability_name="cascade_test",
        )
        created = await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        # Verify capability exists
        fetched = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        assert fetched is not None
        
        # Delete the agent type
        await AgentTypeDAO.delete(test_agent_type.id, session=db_session)
        
        # Verify capability is also deleted via cascade
        fetched_after = await AgentCapabilityDAO.get_by_id(created.id, session=db_session)
        assert fetched_after is None
    
    async def test_multiple_capabilities_per_agent_type(
        self, db_session: AsyncSession, test_agent_type: AgentType
    ):
        """Test that an agent type can have multiple capabilities."""
        capabilities_data = [
            ("web_search", "Search the web"),
            ("summarization", "Summarize text"),
            ("translation", "Translate text"),
        ]
        
        for name, desc in capabilities_data:
            capability_create = AgentCapabilityCreate(
                agent_type_id=test_agent_type.id,
                capability_name=name,
                description=desc,
            )
            await AgentCapabilityDAO.create(capability_create, session=db_session)
        
        capabilities = await AgentCapabilityDAO.get_by_agent_type_id(
            test_agent_type.id, session=db_session
        )
        
        assert len(capabilities) == 3
        names = {c.capability_name for c in capabilities}
        assert names == {"web_search", "summarization", "translation"}