# pyright: reportMissingImports=false
"""
Tests for LLMLevelEndpointDAO database operations.

This module tests CRUD operations for LLMLevelEndpointDAO following the DAO pattern.
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
    LLMLevelEndpointCreate, LLMLevelEndpoint, LLMLevelEndpointUpdate,
    LLMEndpointCreate, LLMEndpoint, LLMEndpointGroupCreate, LLMEndpointGroup,
)
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dao.llm_endpoint_dao import LLMEndpointDAO
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
async def clean_llm_level_endpoints(db_session: AsyncSession) -> AsyncGenerator[None, None]:
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


@pytest_asyncio.fixture
async def test_user(
    db_session: AsyncSession, clean_llm_level_endpoints: None
) -> UserEntity:
    """Create a test user for foreign key relationships."""
    unique_id = str(uuid4())[:8]
    user = UserEntity(
        username=f"llm_lvl_test_{unique_id}",
        email=f"llm_lvl_test_{unique_id}@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_endpoint(
    db_session: AsyncSession, test_user: UserEntity
) -> LLMEndpoint:
    """Create a test endpoint for foreign key relationships."""
    endpoint_create = LLMEndpointCreate(
        user_id=test_user.id,
        name="Level Test Endpoint",
        base_url="https://level.example.com",
        api_key_encrypted="level_key",
        model_name="gpt-4",
    )
    endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
    return endpoint


@pytest_asyncio.fixture
async def test_group(
    db_session: AsyncSession, test_user: UserEntity
) -> LLMEndpointGroup:
    """Create a test group for foreign key relationships."""
    group_create = LLMEndpointGroupCreate(
        user_id=test_user.id,
        name="Level Test Group",
    )
    group = await LLMEndpointGroupDAO.create(group_create, session=db_session)
    return group


class TestLLMLevelEndpointDAOCreate:
    """Test create operations for LLMLevelEndpointDAO."""
    
    async def test_create_level_endpoint_with_minimal_fields(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test creating a level endpoint with only required fields."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
        )
        
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        assert created is not None
        assert created.id is not None
        assert isinstance(created.id, UUID)
        assert created.group_id == test_group.id
        assert created.endpoint_id == test_endpoint.id
        assert created.difficulty_level == 2
        assert created.involves_secrets is False  # Default
        assert created.priority == 0  # Default
        assert created.is_active is True  # Default
        assert created.created_at is not None
    
    async def test_create_level_endpoint_with_all_fields(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test creating a level endpoint with all fields."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=3,
            involves_secrets=True,
            priority=100,
            is_active=False,
        )
        
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        assert created is not None
        assert created.difficulty_level == 3
        assert created.involves_secrets is True
        assert created.priority == 100
        assert created.is_active is False
    
    async def test_create_level_endpoint_returns_dto(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test that create returns an LLMLevelEndpoint DTO."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=1,
        )
        
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        assert isinstance(created, LLMLevelEndpoint)
    
    async def test_create_level_endpoint_all_difficulty_levels(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        clean_llm_level_endpoints: None,
    ):
        """Test creating level endpoints for all difficulty levels (1, 2, 3)."""
        for level in [1, 2, 3]:
            # Create unique endpoint and group for each level
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"Level {level} Endpoint",
                base_url=f"https://level{level}.example.com",
                api_key_encrypted=f"level{level}_key",
                model_name="gpt-4",
            )
            endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
            
            group_create = LLMEndpointGroupCreate(
                user_id=test_user.id,
                name=f"Level {level} Group",
            )
            group = await LLMEndpointGroupDAO.create(group_create, session=db_session)
            
            level_create = LLMLevelEndpointCreate(
                group_id=group.id,
                endpoint_id=endpoint.id,
                difficulty_level=level,
            )
            
            created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
            assert created.difficulty_level == level


class TestLLMLevelEndpointDAOGetById:
    """Test get_by_id operations for LLMLevelEndpointDAO."""
    
    async def test_get_by_id_returns_level_endpoint(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test retrieving a level endpoint by ID."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        fetched = await LLMLevelEndpointDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.difficulty_level == 2
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        result = await LLMLevelEndpointDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test that get_by_id returns an LLMLevelEndpoint DTO."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=1,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        fetched = await LLMLevelEndpointDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, LLMLevelEndpoint)


class TestLLMLevelEndpointDAOGetByGroupId:
    """Test get_by_group_id operations for LLMLevelEndpointDAO."""
    
    async def test_get_by_group_id_returns_level_endpoints(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test retrieving level endpoints by group ID."""
        for i in range(3):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"Group Test Endpoint {i}",
                base_url=f"https://grouptest{i}.example.com",
                api_key_encrypted=f"group_key_{i}",
                model_name="gpt-4",
            )
            endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
            
            level_create = LLMLevelEndpointCreate(
                group_id=test_group.id,
                endpoint_id=endpoint.id,
                difficulty_level=(i % 3) + 1,
            )
            await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        level_endpoints = await LLMLevelEndpointDAO.get_by_group_id(
            test_group.id, session=db_session
        )
        
        assert len(level_endpoints) == 3
        for le in level_endpoints:
            assert le.group_id == test_group.id
    
    async def test_get_by_group_id_empty_returns_empty_list(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that get_by_group_id returns empty list for group with no endpoints."""
        from uuid import uuid4
        
        level_endpoints = await LLMLevelEndpointDAO.get_by_group_id(
            uuid4(), session=db_session
        )
        
        assert level_endpoints == []


class TestLLMLevelEndpointDAOGetByEndpointId:
    """Test get_by_endpoint_id operations for LLMLevelEndpointDAO."""
    
    async def test_get_by_endpoint_id_returns_level_endpoint(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        test_endpoint: LLMEndpoint,
        clean_llm_level_endpoints: None,
    ):
        """Test retrieving level endpoint by endpoint ID (should be unique)."""
        group_create = LLMEndpointGroupCreate(
            user_id=test_user.id,
            name="Endpoint Lookup Group",
        )
        group = await LLMEndpointGroupDAO.create(group_create, session=db_session)
        
        level_create = LLMLevelEndpointCreate(
            group_id=group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
        )
        await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        fetched = await LLMLevelEndpointDAO.get_by_endpoint_id(
            test_endpoint.id, session=db_session
        )
        
        assert fetched is not None
        assert fetched.endpoint_id == test_endpoint.id
    
    async def test_get_by_endpoint_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that get_by_endpoint_id returns None for nonexistent endpoint."""
        from uuid import uuid4
        
        result = await LLMLevelEndpointDAO.get_by_endpoint_id(uuid4(), session=db_session)
        
        assert result is None


class TestLLMLevelEndpointDAOGetAll:
    """Test get_all operations for LLMLevelEndpointDAO."""
    
    async def test_get_all_returns_all_level_endpoints(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test retrieving all level endpoints."""
        for i in range(3):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"All Test Endpoint {i}",
                base_url=f"https://alltest{i}.example.com",
                api_key_encrypted=f"all_key_{i}",
                model_name="gpt-4",
            )
            endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
            
            level_create = LLMLevelEndpointCreate(
                group_id=test_group.id,
                endpoint_id=endpoint.id,
                difficulty_level=(i % 3) + 1,
            )
            await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        level_endpoints = await LLMLevelEndpointDAO.get_all(session=db_session)
        
        assert len(level_endpoints) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that get_all returns empty list when no level endpoints exist."""
        level_endpoints = await LLMLevelEndpointDAO.get_all(session=db_session)
        
        assert level_endpoints == []
    
    async def test_get_all_with_pagination(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"Page Endpoint {i}",
                base_url=f"https://page{i}.example.com",
                api_key_encrypted=f"page_key_{i}",
                model_name="gpt-4",
            )
            endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
            
            level_create = LLMLevelEndpointCreate(
                group_id=test_group.id,
                endpoint_id=endpoint.id,
                difficulty_level=1,
            )
            await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        # Test limit
        limited = await LLMLevelEndpointDAO.get_all(limit=2, session=db_session)
        assert len(limited) == 2
        
        # Test offset
        offset = await LLMLevelEndpointDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(offset) == 2
    
    async def test_get_all_with_active_filter(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test get_all with active_only filter."""
        # Create active level endpoint
        endpoint_create1 = LLMEndpointCreate(
            user_id=test_user.id,
            name="Active Level Endpoint",
            base_url="https://activelevel.example.com",
            api_key_encrypted="active_level_key",
            model_name="gpt-4",
        )
        endpoint1 = await LLMEndpointDAO.create(endpoint_create1, session=db_session)
        
        level_create1 = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=endpoint1.id,
            difficulty_level=1,
            is_active=True,
        )
        await LLMLevelEndpointDAO.create(level_create1, session=db_session)
        
        # Create inactive level endpoint
        endpoint_create2 = LLMEndpointCreate(
            user_id=test_user.id,
            name="Inactive Level Endpoint",
            base_url="https://inactivelevel.example.com",
            api_key_encrypted="inactive_level_key",
            model_name="gpt-4",
        )
        endpoint2 = await LLMEndpointDAO.create(endpoint_create2, session=db_session)
        
        level_create2 = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=endpoint2.id,
            difficulty_level=1,
            is_active=False,
        )
        await LLMLevelEndpointDAO.create(level_create2, session=db_session)
        
        # Get all active
        active = await LLMLevelEndpointDAO.get_all(active_only=True, session=db_session)
        assert len(active) == 1
        assert active[0].is_active is True
        
        # Get all
        all_level_endpoints = await LLMLevelEndpointDAO.get_all(
            active_only=False, session=db_session
        )
        assert len(all_level_endpoints) == 2


class TestLLMLevelEndpointDAOUpdate:
    """Test update operations for LLMLevelEndpointDAO."""
    
    async def test_update_difficulty_level(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test updating a level endpoint's difficulty level."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=1,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        level_update = LLMLevelEndpointUpdate(
            id=created.id,
            difficulty_level=3,
        )
        updated = await LLMLevelEndpointDAO.update(level_update, session=db_session)
        
        assert updated is not None
        assert updated.difficulty_level == 3
    
    async def test_update_priority(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test updating a level endpoint's priority."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
            priority=0,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        level_update = LLMLevelEndpointUpdate(
            id=created.id,
            priority=100,
        )
        updated = await LLMLevelEndpointDAO.update(level_update, session=db_session)
        
        assert updated is not None
        assert updated.priority == 100
    
    async def test_update_involves_secrets(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test updating a level endpoint's involves_secrets flag."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
            involves_secrets=False,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        level_update = LLMLevelEndpointUpdate(
            id=created.id,
            involves_secrets=True,
        )
        updated = await LLMLevelEndpointDAO.update(level_update, session=db_session)
        
        assert updated is not None
        assert updated.involves_secrets is True
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that updating a nonexistent level endpoint returns None."""
        from uuid import uuid4
        
        level_update = LLMLevelEndpointUpdate(
            id=uuid4(),
            difficulty_level=2,
        )
        
        result = await LLMLevelEndpointDAO.update(level_update, session=db_session)
        
        assert result is None


class TestLLMLevelEndpointDAODelete:
    """Test delete operations for LLMLevelEndpointDAO."""
    
    async def test_delete_existing_level_endpoint(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test deleting an existing level endpoint."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        result = await LLMLevelEndpointDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify deleted
        fetched = await LLMLevelEndpointDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that deleting a nonexistent level endpoint returns False."""
        from uuid import uuid4
        
        result = await LLMLevelEndpointDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestLLMLevelEndpointDAOExists:
    """Test exists operations for LLMLevelEndpointDAO."""
    
    async def test_exists_returns_true_for_existing(
        self,
        db_session: AsyncSession,
        test_endpoint: LLMEndpoint,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test that exists returns True for existing level endpoint."""
        level_create = LLMLevelEndpointCreate(
            group_id=test_group.id,
            endpoint_id=test_endpoint.id,
            difficulty_level=2,
        )
        created = await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        result = await LLMLevelEndpointDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that exists returns False for nonexistent level endpoint."""
        from uuid import uuid4
        
        result = await LLMLevelEndpointDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestLLMLevelEndpointDAOCount:
    """Test count operations for LLMLevelEndpointDAO."""
    
    async def test_count_returns_correct_number(
        self,
        db_session: AsyncSession,
        test_user: UserEntity,
        test_group: LLMEndpointGroup,
        clean_llm_level_endpoints: None,
    ):
        """Test that count returns the correct number of level endpoints."""
        for i in range(3):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"Count Endpoint {i}",
                base_url=f"https://count{i}.example.com",
                api_key_encrypted=f"count_key_{i}",
                model_name="gpt-4",
            )
            endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
            
            level_create = LLMLevelEndpointCreate(
                group_id=test_group.id,
                endpoint_id=endpoint.id,
                difficulty_level=1,
            )
            await LLMLevelEndpointDAO.create(level_create, session=db_session)
        
        count = await LLMLevelEndpointDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_returns_zero(
        self, db_session: AsyncSession, clean_llm_level_endpoints: None
    ):
        """Test that count returns 0 for empty table."""
        count = await LLMLevelEndpointDAO.count(session=db_session)
        
        assert count == 0