# pyright: reportMissingImports=false
"""
Tests for AgentInstanceDAO database operations.

This module tests CRUD operations for AgentInstanceDAO following the DAO pattern.
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
from db.dto.agent_dto import (
    AgentInstanceCreate,
    AgentInstance,
    AgentInstanceUpdate,
    AgentTypeCreate,
)
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.user_dao import UserDAO
from db.dto.user_dto import UserCreate
from db.entity.agent_entity import AgentType as AgentTypeEntity, AgentInstance as AgentInstanceEntity
from db.entity.user_entity import User as UserEntity


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
async def sample_user(db_session: AsyncSession) -> UserEntity:
    """Create a sample user for testing."""
    user_create = UserCreate(
        username=f"agentuser_{uuid4().hex[:8]}",
        email=f"agent_{uuid4().hex[:8]}@example.com",
    )
    user_dto = await UserDAO.create(user_create, session=db_session)
    
    # Fetch the entity for relationship purposes
    from sqlalchemy import select
    result = await db_session.execute(
        select(UserEntity).where(UserEntity.id == user_dto.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def sample_agent_type(db_session: AsyncSession) -> AgentTypeEntity:
    """Create a sample agent type for testing."""
    agent_type_create = AgentTypeCreate(
        name=f"test_type_{uuid4().hex[:8]}",
        description="Test agent type",
    )
    agent_type_dto = await AgentTypeDAO.create(agent_type_create, session=db_session)
    
    # Fetch the entity for relationship purposes
    from sqlalchemy import select
    result = await db_session.execute(
        select(AgentTypeEntity).where(AgentTypeEntity.id == agent_type_dto.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def clean_agent_instances_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean agent_instances table before and after tests."""
    await db_session.execute(delete(AgentInstanceEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(AgentInstanceEntity))
    await db_session.commit()


class TestAgentInstanceDAOCreate:
    """Test create operations for AgentInstanceDAO."""
    
    async def test_create_agent_instance_with_minimal_fields(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test creating an agent instance with only required fields."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        assert created is not None
        assert created.id is not None
        assert isinstance(created.id, UUID)
        assert created.agent_type_id == sample_agent_type.id
        assert created.user_id == sample_user.id
        assert created.name is None
        assert created.status == "idle"  # Default value
        assert created.config is None
        assert created.last_heartbeat_at is None
        assert created.created_at is not None
        assert created.updated_at is not None
        assert isinstance(created.created_at, datetime)
        assert isinstance(created.updated_at, datetime)
    
    async def test_create_agent_instance_with_all_fields(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test creating an agent instance with all fields specified."""
        now = datetime.now(timezone.utc)
        
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="TestInstance",
            status="busy",
            config={"timeout": 30, "retries": 3},
            last_heartbeat_at=now,
        )
        
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        assert created is not None
        assert created.agent_type_id == sample_agent_type.id
        assert created.user_id == sample_user.id
        assert created.name == "TestInstance"
        assert created.status == "busy"
        assert created.config == {"timeout": 30, "retries": 3}
        assert created.last_heartbeat_at is not None
    
    async def test_create_agent_instance_returns_dto(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that create returns an AgentInstance DTO, not an entity."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        assert isinstance(created, AgentInstance)
    
    async def test_create_with_invalid_agent_type_raises_error(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        clean_agent_instances_table: None,
    ):
        """Test that creating with invalid agent_type_id raises error."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=uuid4(),  # Non-existent
            user_id=sample_user.id,
        )
        
        with pytest.raises(Exception):  # ForeignKey violation
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)
    
    async def test_create_with_invalid_user_raises_error(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that creating with invalid user_id raises error."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=uuid4(),  # Non-existent
        )
        
        with pytest.raises(Exception):  # ForeignKey violation
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)


class TestAgentInstanceDAOGetById:
    """Test get_by_id operations for AgentInstanceDAO."""
    
    async def test_get_by_id_returns_agent_instance(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test retrieving an agent instance by ID."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="GetTest",
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        fetched = await AgentInstanceDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "GetTest"
    
    async def test_get_by_id_nonexistent_returns_none(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        result = await AgentInstanceDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that get_by_id returns an AgentInstance DTO."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        fetched = await AgentInstanceDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, AgentInstance)


class TestAgentInstanceDAOGetByUserId:
    """Test get_by_user_id operations for AgentInstanceDAO."""
    
    async def test_get_by_user_id_returns_instances(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test retrieving agent instances by user_id."""
        for i in range(3):
            agent_instance_create = AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name=f"UserInstance{i}",
            )
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        instances = await AgentInstanceDAO.get_by_user_id(sample_user.id, session=db_session)
        
        assert len(instances) == 3
        for instance in instances:
            assert instance.user_id == sample_user.id
    
    async def test_get_by_user_id_no_instances_returns_empty(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that get_by_user_id returns empty list for user with no instances."""
        instances = await AgentInstanceDAO.get_by_user_id(uuid4(), session=db_session)
        
        assert instances == []


class TestAgentInstanceDAOGetByAgentTypeId:
    """Test get_by_agent_type_id operations for AgentInstanceDAO."""
    
    async def test_get_by_agent_type_id_returns_instances(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test retrieving agent instances by agent_type_id."""
        for i in range(2):
            agent_instance_create = AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name=f"TypeInstance{i}",
            )
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        instances = await AgentInstanceDAO.get_by_agent_type_id(
            sample_agent_type.id, session=db_session
        )
        
        assert len(instances) == 2
        for instance in instances:
            assert instance.agent_type_id == sample_agent_type.id
    
    async def test_get_by_agent_type_id_no_instances_returns_empty(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that get_by_agent_type_id returns empty list for type with no instances."""
        instances = await AgentInstanceDAO.get_by_agent_type_id(uuid4(), session=db_session)
        
        assert instances == []


class TestAgentInstanceDAOGetAll:
    """Test get_all operations for AgentInstanceDAO."""
    
    async def test_get_all_returns_all_instances(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test retrieving all agent instances."""
        for i in range(3):
            agent_instance_create = AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name=f"AllInstance{i}",
            )
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        instances = await AgentInstanceDAO.get_all(session=db_session)
        
        assert len(instances) == 3
        names = {inst.name for inst in instances}
        assert names == {"AllInstance0", "AllInstance1", "AllInstance2"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that get_all returns empty list when no instances exist."""
        instances = await AgentInstanceDAO.get_all(session=db_session)
        
        assert instances == []
    
    async def test_get_all_with_pagination(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            agent_instance_create = AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name=f"PageInstance{i}",
            )
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        # Test limit
        instances_limited = await AgentInstanceDAO.get_all(limit=2, session=db_session)
        assert len(instances_limited) == 2
        
        # Test offset
        instances_offset = await AgentInstanceDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(instances_offset) == 2
        
        # Verify different instances returned
        ids_limited = {inst.id for inst in instances_limited}
        ids_offset = {inst.id for inst in instances_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that get_all returns AgentInstance DTOs."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        instances = await AgentInstanceDAO.get_all(session=db_session)
        
        assert len(instances) == 1
        assert isinstance(instances[0], AgentInstance)
    
    async def test_get_all_by_status(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test get_all with status filter."""
        # Create instances with different statuses
        await AgentInstanceDAO.create(
            AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name="IdleInstance",
                status="idle",
            ),
            session=db_session
        )
        await AgentInstanceDAO.create(
            AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name="BusyInstance",
                status="busy",
            ),
            session=db_session
        )
        
        idle_instances = await AgentInstanceDAO.get_all(status="idle", session=db_session)
        
        assert len(idle_instances) == 1
        assert idle_instances[0].status == "idle"


class TestAgentInstanceDAOUpdate:
    """Test update operations for AgentInstanceDAO."""
    
    async def test_update_agent_instance_name(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test updating an agent instance's name."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            name="BeforeUpdate",
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        # Wait a tiny bit to ensure timestamp changes
        await asyncio.sleep(0.01)
        
        agent_instance_update = AgentInstanceUpdate(
            id=created.id,
            name="AfterUpdate",
        )
        updated = await AgentInstanceDAO.update(agent_instance_update, session=db_session)
        
        assert updated is not None
        assert updated.name == "AfterUpdate"
        assert updated.updated_at > created.updated_at
    
    async def test_update_agent_instance_status(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test updating an agent instance's status."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status="idle",
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        agent_instance_update = AgentInstanceUpdate(
            id=created.id,
            status="busy",
        )
        updated = await AgentInstanceDAO.update(agent_instance_update, session=db_session)
        
        assert updated is not None
        assert updated.status == "busy"
    
    async def test_update_agent_instance_config(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test updating an agent instance's config."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        new_config = {"timeout": 60, "retries": 5}
        agent_instance_update = AgentInstanceUpdate(
            id=created.id,
            config=new_config,
        )
        updated = await AgentInstanceDAO.update(agent_instance_update, session=db_session)
        
        assert updated is not None
        assert updated.config == new_config
    
    async def test_update_agent_instance_heartbeat(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test updating an agent instance's last_heartbeat_at."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        now = datetime.now(timezone.utc)
        agent_instance_update = AgentInstanceUpdate(
            id=created.id,
            last_heartbeat_at=now,
        )
        updated = await AgentInstanceDAO.update(agent_instance_update, session=db_session)
        
        assert updated is not None
        assert updated.last_heartbeat_at is not None
    
    async def test_update_nonexistent_returns_none(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that updating a nonexistent instance returns None."""
        agent_instance_update = AgentInstanceUpdate(
            id=uuid4(),
            name="Nonexistent",
        )
        
        result = await AgentInstanceDAO.update(agent_instance_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that update returns an AgentInstance DTO."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        agent_instance_update = AgentInstanceUpdate(
            id=created.id,
            name="Updated",
        )
        updated = await AgentInstanceDAO.update(agent_instance_update, session=db_session)
        
        assert isinstance(updated, AgentInstance)


class TestAgentInstanceDAODelete:
    """Test delete operations for AgentInstanceDAO."""
    
    async def test_delete_existing_instance(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test deleting an existing agent instance."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        result = await AgentInstanceDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify instance is deleted
        fetched = await AgentInstanceDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that deleting a nonexistent instance returns False."""
        result = await AgentInstanceDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestAgentInstanceDAOExists:
    """Test exists operations for AgentInstanceDAO."""
    
    async def test_exists_returns_true_for_existing(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that exists returns True for existing instance."""
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        result = await AgentInstanceDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that exists returns False for nonexistent instance."""
        result = await AgentInstanceDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestAgentInstanceDAOCount:
    """Test count operations for AgentInstanceDAO."""
    
    async def test_count_returns_correct_number(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that count returns the correct number of instances."""
        for i in range(3):
            agent_instance_create = AgentInstanceCreate(
                agent_type_id=sample_agent_type.id,
                user_id=sample_user.id,
                name=f"CountInstance{i}",
            )
            await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        count = await AgentInstanceDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self,
        db_session: AsyncSession,
        clean_agent_instances_table: None,
    ):
        """Test that count returns 0 for empty table."""
        count = await AgentInstanceDAO.count(session=db_session)
        
        assert count == 0


class TestAgentInstanceDAOJSONBFields:
    """Test JSONB field handling for AgentInstanceDAO."""
    
    async def test_config_jsonb_persistence(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that config JSONB field persists correctly."""
        config = {
            "timeout": 30,
            "retries": 3,
            "model": "gpt-4",
            "options": {"temperature": 0.7},
        }
        
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            config=config,
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        fetched = await AgentInstanceDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.config == config


class TestAgentInstanceDAOStatusTransitions:
    """Test status transitions for agent instances."""
    
    async def test_status_transitions(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that status can be updated to different values."""
        # Create with idle status
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=sample_user.id,
            status="idle",
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        assert created.status == "idle"
        
        # Transition to busy
        updated = await AgentInstanceDAO.update(
            AgentInstanceUpdate(id=created.id, status="busy"),
            session=db_session
        )
        assert updated.status == "busy"
        
        # Transition to error
        updated = await AgentInstanceDAO.update(
            AgentInstanceUpdate(id=created.id, status="error"),
            session=db_session
        )
        assert updated.status == "error"
        
        # Transition to offline
        updated = await AgentInstanceDAO.update(
            AgentInstanceUpdate(id=created.id, status="offline"),
            session=db_session
        )
        assert updated.status == "offline"
        
        # Transition back to idle
        updated = await AgentInstanceDAO.update(
            AgentInstanceUpdate(id=created.id, status="idle"),
            session=db_session
        )
        assert updated.status == "idle"


class TestAgentInstanceDAOCascadeDelete:
    """Test cascade delete behavior."""
    
    async def test_delete_user_cascades_to_instances(
        self,
        db_session: AsyncSession,
        sample_agent_type: AgentTypeEntity,
        clean_agent_instances_table: None,
    ):
        """Test that deleting a user cascades to agent instances."""
        # Create a user
        user_create = UserCreate(
            username=f"cascade_user_{uuid4().hex[:8]}",
            email=f"cascade_{uuid4().hex[:8]}@example.com",
        )
        user = await UserDAO.create(user_create, session=db_session)
        
        # Create an agent instance for the user
        agent_instance_create = AgentInstanceCreate(
            agent_type_id=sample_agent_type.id,
            user_id=user.id,
            name="CascadeInstance",
        )
        created = await AgentInstanceDAO.create(agent_instance_create, session=db_session)
        
        # Delete the user
        await UserDAO.delete(user.id, session=db_session)
        
        # Verify the instance is also deleted
        fetched = await AgentInstanceDAO.get_by_id(created.id, session=db_session)
        assert fetched is None