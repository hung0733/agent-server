# pyright: reportMissingImports=false
"""
Tests for LLMEndpointGroupDAO database operations.

This module tests CRUD operations for LLMEndpointGroupDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.llm_endpoint_dto import (
    LLMEndpointGroupCreate, LLMEndpointGroup, LLMEndpointGroupUpdate
)
from db.dao.llm_endpoint_group_dao import LLMEndpointGroupDAO
from db.entity.user_entity import User as UserEntity
from db.entity.llm_endpoint_entity import (
    LLMEndpoint as LLMEndpointEntity,
    LLMEndpointGroup as LLMEndpointGroupEntity,
    LLMLevelEndpoint as LLMLevelEndpointEntity,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
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


from uuid import uuid4


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> UserEntity:
    """Create a test user for foreign key relationships."""
    unique_id = str(uuid4())[:8]
    user = UserEntity(
        username=f"llm_grp_test_{unique_id}",
        email=f"llm_grp_test_{unique_id}@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def clean_llm_endpoint_groups(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean LLM endpoint related tables before and after tests."""
    await db_session.execute(delete(LLMLevelEndpointEntity))
    await db_session.execute(delete(LLMEndpointEntity))
    await db_session.execute(delete(LLMEndpointGroupEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(LLMLevelEndpointEntity))
    await db_session.execute(delete(LLMEndpointEntity))
    await db_session.execute(delete(LLMEndpointGroupEntity))
    await db_session.commit()


class TestLLMEndpointGroupDAOCreate:
    """Test create operations for LLMEndpointGroupDAO."""
    
    async def test_create_group_with_minimal_fields(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test creating a group with only required fields."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Test Group",
        )
        
        created_group = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        assert created_group is not None
        assert created_group.id is not None
        assert isinstance(created_group.id, UUID)
        assert created_group.user_id == test_user.id
        assert created_group.name == "Test Group"
        assert created_group.description is None
        assert created_group.is_default is False  # Default value
        assert created_group.created_at is not None
        assert created_group.updated_at is not None
    
    async def test_create_group_with_all_fields(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test creating a group with all fields specified."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Full Group",
            description="A complete group with description",
            is_default=True,
        )
        
        created_group = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        assert created_group is not None
        assert created_group.name == "Full Group"
        assert created_group.description == "A complete group with description"
        assert created_group.is_default is True
    
    async def test_create_group_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test that create returns an LLMEndpointGroup DTO."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="DTO Test Group",
        )
        
        created_group = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        assert isinstance(created_group, LLMEndpointGroup)
    
    async def test_create_duplicate_name_per_user_raises_error(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test that duplicate names per user raise IntegrityError."""
        group_create1 = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Duplicate Name",
        )
        group_create2 = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Duplicate Name",
        )
        
        await LLMEndpointGroupDAO.create(group_create1, session=db_session)
        
        with pytest.raises(Exception):  # IntegrityError
            await LLMEndpointGroupDAO.create(group_create2, session=db_session)


class TestLLMEndpointGroupDAOGetById:
    """Test get_by_id operations for LLMEndpointGroupDAO."""
    
    async def test_get_by_id_returns_group(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test retrieving a group by ID."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Get Test Group",
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        fetched = await LLMEndpointGroupDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Get Test Group"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        result = await LLMEndpointGroupDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test that get_by_id returns an LLMEndpointGroup DTO."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="DTO Get Test",
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        fetched = await LLMEndpointGroupDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, LLMEndpointGroup)


class TestLLMEndpointGroupDAOGetByUserId:
    """Test get_by_user_id operations for LLMEndpointGroupDAO."""
    
    async def test_get_by_user_id_returns_groups(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test retrieving groups by user ID."""
        for i in range(3):
            group_create = LLMEndpointGroupCreate(
                user_id=test_user.id,
                name=f"User Group {i}",
            )
            await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        groups = await LLMEndpointGroupDAO.get_by_user_id(test_user.id, session=db_session)
        
        assert len(groups) == 3
        for g in groups:
            assert g.user_id == test_user.id
    
    async def test_get_by_user_id_empty_returns_empty_list(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that get_by_user_id returns empty list for user with no groups."""
        from uuid import uuid4
        
        groups = await LLMEndpointGroupDAO.get_by_user_id(uuid4(), session=db_session)
        
        assert groups == []


class TestLLMEndpointGroupDAOGetDefaultGroup:
    """Test get_default_group operations for LLMEndpointGroupDAO."""
    
    async def test_get_default_group_returns_default(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test retrieving the default group for a user."""
        # Create non-default group
        group_create1 = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Non-default Group",
            is_default=False,
        )
        await LLMEndpointGroupDAO.create(group_create1, session=db_session)
        
        # Create default group
        group_create2 = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Default Group",
            is_default=True,
        )
        created_default = await LLMEndpointGroupDAO.create(group_create2, session=db_session)
        
        fetched = await LLMEndpointGroupDAO.get_default_group(test_user.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created_default.id
        assert fetched.is_default is True
    
    async def test_get_default_group_no_default_returns_none(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test that get_default_group returns None if no default exists."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Non-default Only",
            is_default=False,
        )
        await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        fetched = await LLMEndpointGroupDAO.get_default_group(test_user.id, session=db_session)
        
        assert fetched is None


class TestLLMEndpointGroupDAOGetAll:
    """Test get_all operations for LLMEndpointGroupDAO."""
    
    async def test_get_all_returns_all_groups(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test retrieving all groups."""
        for i in range(3):
            group_create = LLMEndpointGroupCreate(
                user_id=test_user.id,
                name=f"All Group {i}",
            )
            await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        groups = await LLMEndpointGroupDAO.get_all(session=db_session)
        
        assert len(groups) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that get_all returns empty list when no groups exist."""
        groups = await LLMEndpointGroupDAO.get_all(session=db_session)
        
        assert groups == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            group_create = LLMEndpointGroupCreate(
                user_id=test_user.id,
                name=f"Page Group {i}",
            )
            await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        # Test limit
        groups_limited = await LLMEndpointGroupDAO.get_all(limit=2, session=db_session)
        assert len(groups_limited) == 2
        
        # Test offset
        groups_offset = await LLMEndpointGroupDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(groups_offset) == 2


class TestLLMEndpointGroupDAOUpdate:
    """Test update operations for LLMEndpointGroupDAO."""
    
    async def test_update_group_name(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test updating a group's name."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Before Update",
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        await asyncio.sleep(0.01)
        
        group_update = LLMEndpointGroupUpdate(
            id=created.id,
            name="After Update",
        )
        updated = await LLMEndpointGroupDAO.update(group_update, session=db_session)
        
        assert updated is not None
        assert updated.name == "After Update"
        assert updated.updated_at > created.updated_at
    
    async def test_update_group_description(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test updating a group's description."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Description Test",
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        group_update = LLMEndpointGroupUpdate(
            id=created.id,
            description="Updated description",
        )
        updated = await LLMEndpointGroupDAO.update(group_update, session=db_session)
        
        assert updated is not None
        assert updated.description == "Updated description"
    
    async def test_update_group_is_default(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test updating a group's default status."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Default Test",
            is_default=False,
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        group_update = LLMEndpointGroupUpdate(
            id=created.id,
            is_default=True,
        )
        updated = await LLMEndpointGroupDAO.update(group_update, session=db_session)
        
        assert updated is not None
        assert updated.is_default is True
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that updating a nonexistent group returns None."""
        from uuid import uuid4
        
        group_update = LLMEndpointGroupUpdate(
            id=uuid4(),
            name="Nonexistent",
        )
        
        result = await LLMEndpointGroupDAO.update(group_update, session=db_session)
        
        assert result is None


class TestLLMEndpointGroupDAODelete:
    """Test delete operations for LLMEndpointGroupDAO."""
    
    async def test_delete_existing_group(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test deleting an existing group."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Delete Test",
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        result = await LLMEndpointGroupDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify deleted
        fetched = await LLMEndpointGroupDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that deleting a nonexistent group returns False."""
        from uuid import uuid4
        
        result = await LLMEndpointGroupDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestLLMEndpointGroupDAOExists:
    """Test exists operations for LLMEndpointGroupDAO."""
    
    async def test_exists_returns_true_for_existing(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test that exists returns True for existing group."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Exists Test",
        )
        created = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        result = await LLMEndpointGroupDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that exists returns False for nonexistent group."""
        from uuid import uuid4
        
        result = await LLMEndpointGroupDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestLLMEndpointGroupDAOCount:
    """Test count operations for LLMEndpointGroupDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoint_groups: None
    ):
        """Test that count returns the correct number of groups."""
        for i in range(3):
            group_create = LLMEndpointGroupCreate(
                user_id=test_user.id,
                name=f"Count Group {i}",
            )
            await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        count = await LLMEndpointGroupDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_returns_zero(
        self, db_session: AsyncSession, clean_llm_endpoint_groups: None
    ):
        """Test that count returns 0 for empty table."""
        count = await LLMEndpointGroupDAO.count(session=db_session)
        
        assert count == 0