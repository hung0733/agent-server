# pyright: reportMissingImports=false
"""
Tests for AgentTypeDAO database operations.

This module tests CRUD operations for AgentTypeDAO following the DAO pattern.
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
from db.dto.agent_dto import AgentTypeCreate, AgentType, AgentTypeUpdate
from db.dao.agent_type_dao import AgentTypeDAO
from db.entity.agent_entity import AgentType as AgentTypeEntity


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation by cleaning data rather than dropping tables.
    """
    import os
    
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
async def clean_agent_types_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean agent_types table before and after tests."""
    await db_session.execute(delete(AgentTypeEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(AgentTypeEntity))
    await db_session.commit()


class TestAgentTypeDAOCreate:
    """Test create operations for AgentTypeDAO."""
    
    async def test_create_agent_type_with_minimal_fields(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test creating an agent type with only required fields."""
        agent_type_create = AgentTypeCreate(
            name="TestAgent",
        )
        
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        assert created is not None
        assert created.id is not None
        assert isinstance(created.id, UUID)
        assert created.name == "TestAgent"
        assert created.description is None
        assert created.capabilities is None
        assert created.default_config is None
        assert created.is_active is True  # Default value
        assert created.created_at is not None
        assert created.updated_at is not None
        assert isinstance(created.created_at, datetime)
        assert isinstance(created.updated_at, datetime)
    
    async def test_create_agent_type_with_all_fields(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test creating an agent type with all fields specified."""
        agent_type_create = AgentTypeCreate(
            name="FullAgent",
            description="A fully configured agent type",
            capabilities={"web_search": True, "summarization": True},
            default_config={"max_results": 10, "timeout": 30},
            is_active=False,
        )
        
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        assert created is not None
        assert created.name == "FullAgent"
        assert created.description == "A fully configured agent type"
        assert created.capabilities == {"web_search": True, "summarization": True}
        assert created.default_config == {"max_results": 10, "timeout": 30}
        assert created.is_active is False
    
    async def test_create_agent_type_returns_dto(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that create returns an AgentType DTO, not an entity."""
        agent_type_create = AgentTypeCreate(
            name="DTOTest",
        )
        
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        assert isinstance(created, AgentType)
    
    async def test_create_duplicate_name_raises_error(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that duplicate names raise IntegrityError."""
        agent_type_create1 = AgentTypeCreate(name="DuplicateAgent")
        agent_type_create2 = AgentTypeCreate(name="DuplicateAgent")
        
        await AgentTypeDAO.create(agent_type_create1, session=db_session)
        
        with pytest.raises(Exception):  # IntegrityError
            await AgentTypeDAO.create(agent_type_create2, session=db_session)


class TestAgentTypeDAOGetById:
    """Test get_by_id operations for AgentTypeDAO."""
    
    async def test_get_by_id_returns_agent_type(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test retrieving an agent type by ID."""
        agent_type_create = AgentTypeCreate(
            name="GetTest",
            description="Test retrieval",
        )
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        fetched = await AgentTypeDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "GetTest"
        assert fetched.description == "Test retrieval"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        result = await AgentTypeDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that get_by_id returns an AgentType DTO."""
        agent_type_create = AgentTypeCreate(name="DTOGetTest")
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        fetched = await AgentTypeDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, AgentType)


class TestAgentTypeDAOGetByName:
    """Test get_by_name operations for AgentTypeDAO."""
    
    async def test_get_by_name_returns_agent_type(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test retrieving an agent type by name."""
        agent_type_create = AgentTypeCreate(
            name="NameTest",
            description="Test by name",
        )
        await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        fetched = await AgentTypeDAO.get_by_name("NameTest", session=db_session)
        
        assert fetched is not None
        assert fetched.name == "NameTest"
        assert fetched.description == "Test by name"
    
    async def test_get_by_name_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that get_by_name returns None for nonexistent name."""
        result = await AgentTypeDAO.get_by_name("NonexistentAgent", session=db_session)
        
        assert result is None


class TestAgentTypeDAOGetAll:
    """Test get_all operations for AgentTypeDAO."""
    
    async def test_get_all_returns_all_agent_types(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test retrieving all agent types."""
        for i in range(3):
            agent_type_create = AgentTypeCreate(
                name=f"AllAgent{i}",
                description=f"Agent {i}",
            )
            await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        agent_types = await AgentTypeDAO.get_all(session=db_session)
        
        assert len(agent_types) == 3
        names = {at.name for at in agent_types}
        assert names == {"AllAgent0", "AllAgent1", "AllAgent2"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that get_all returns empty list when no agent types exist."""
        agent_types = await AgentTypeDAO.get_all(session=db_session)
        
        assert agent_types == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            agent_type_create = AgentTypeCreate(name=f"PageAgent{i}")
            await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        # Test limit
        agent_types_limited = await AgentTypeDAO.get_all(limit=2, session=db_session)
        assert len(agent_types_limited) == 2
        
        # Test offset
        agent_types_offset = await AgentTypeDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(agent_types_offset) == 2
        
        # Verify different agent types returned
        ids_limited = {at.id for at in agent_types_limited}
        ids_offset = {at.id for at in agent_types_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that get_all returns AgentType DTOs."""
        agent_type_create = AgentTypeCreate(name="DTOListTest")
        await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        agent_types = await AgentTypeDAO.get_all(session=db_session)
        
        assert len(agent_types) == 1
        assert isinstance(agent_types[0], AgentType)
    
    async def test_get_all_active_only(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test get_all with active_only filter."""
        # Create active and inactive agent types
        await AgentTypeDAO.create(
            AgentTypeCreate(name="ActiveAgent", is_active=True),
            session=db_session
        )
        await AgentTypeDAO.create(
            AgentTypeCreate(name="InactiveAgent", is_active=False),
            session=db_session
        )
        
        active_types = await AgentTypeDAO.get_all(active_only=True, session=db_session)
        
        assert len(active_types) == 1
        assert active_types[0].name == "ActiveAgent"


class TestAgentTypeDAOUpdate:
    """Test update operations for AgentTypeDAO."""
    
    async def test_update_agent_type_description(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test updating an agent type's description."""
        agent_type_create = AgentTypeCreate(
            name="UpdateTest",
            description="Before update",
        )
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        # Wait a tiny bit to ensure timestamp changes
        await asyncio.sleep(0.01)
        
        agent_type_update = AgentTypeUpdate(
            id=created.id,
            description="After update",
        )
        updated = await AgentTypeDAO.update(agent_type_update, session=db_session)
        
        assert updated is not None
        assert updated.name == "UpdateTest"
        assert updated.description == "After update"
        assert updated.updated_at > created.updated_at
    
    async def test_update_agent_type_capabilities(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test updating an agent type's capabilities."""
        agent_type_create = AgentTypeCreate(name="CapUpdateTest")
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        agent_type_update = AgentTypeUpdate(
            id=created.id,
            capabilities={"new_capability": True},
        )
        updated = await AgentTypeDAO.update(agent_type_update, session=db_session)
        
        assert updated is not None
        assert updated.capabilities == {"new_capability": True}
    
    async def test_update_agent_type_is_active(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test updating an agent type's is_active status."""
        agent_type_create = AgentTypeCreate(
            name="ActiveTest",
            is_active=True,
        )
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        agent_type_update = AgentTypeUpdate(
            id=created.id,
            is_active=False,
        )
        updated = await AgentTypeDAO.update(agent_type_update, session=db_session)
        
        assert updated is not None
        assert updated.is_active is False
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that updating a nonexistent agent type returns None."""
        agent_type_update = AgentTypeUpdate(
            id=uuid4(),
            description="Nonexistent",
        )
        
        result = await AgentTypeDAO.update(agent_type_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that update returns an AgentType DTO."""
        agent_type_create = AgentTypeCreate(name="DTOUpdateTest")
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        agent_type_update = AgentTypeUpdate(
            id=created.id,
            description="Updated",
        )
        updated = await AgentTypeDAO.update(agent_type_update, session=db_session)
        
        assert isinstance(updated, AgentType)


class TestAgentTypeDAODelete:
    """Test delete operations for AgentTypeDAO."""
    
    async def test_delete_existing_agent_type(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test deleting an existing agent type."""
        agent_type_create = AgentTypeCreate(name="DeleteTest")
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        result = await AgentTypeDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify agent type is deleted
        fetched = await AgentTypeDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that deleting a nonexistent agent type returns False."""
        result = await AgentTypeDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestAgentTypeDAOExists:
    """Test exists operations for AgentTypeDAO."""
    
    async def test_exists_returns_true_for_existing(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that exists returns True for existing agent type."""
        agent_type_create = AgentTypeCreate(name="ExistsTest")
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        result = await AgentTypeDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that exists returns False for nonexistent agent type."""
        result = await AgentTypeDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestAgentTypeDAOCount:
    """Test count operations for AgentTypeDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that count returns the correct number of agent types."""
        for i in range(3):
            agent_type_create = AgentTypeCreate(name=f"CountAgent{i}")
            await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        count = await AgentTypeDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that count returns 0 for empty table."""
        count = await AgentTypeDAO.count(session=db_session)
        
        assert count == 0


class TestAgentTypeDAOJSONBFields:
    """Test JSONB field handling for AgentTypeDAO."""
    
    async def test_capabilities_jsonb_persistence(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that capabilities JSONB field persists correctly."""
        capabilities = {
            "web_search": True,
            "summarization": True,
            "code_generation": False,
            "max_items": 100,
            "nested": {"key": "value"},
        }
        
        agent_type_create = AgentTypeCreate(
            name="JSONBCapTest",
            capabilities=capabilities,
        )
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        fetched = await AgentTypeDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.capabilities == capabilities
    
    async def test_default_config_jsonb_persistence(
        self, db_session: AsyncSession, clean_agent_types_table: None
    ):
        """Test that default_config JSONB field persists correctly."""
        default_config = {
            "timeout": 30,
            "retries": 3,
            "model": "gpt-4",
            "options": {"temperature": 0.7},
        }
        
        agent_type_create = AgentTypeCreate(
            name="JSONBConfigTest",
            default_config=default_config,
        )
        created = await AgentTypeDAO.create(agent_type_create, session=db_session)
        
        fetched = await AgentTypeDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.default_config == default_config