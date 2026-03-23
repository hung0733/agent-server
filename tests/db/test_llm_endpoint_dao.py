# pyright: reportMissingImports=false
"""
Tests for LLMEndpointDAO database operations.

This module tests CRUD operations for LLMEndpointDAO following the DAO pattern.
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
    LLMEndpointCreate, LLMEndpoint, LLMEndpointUpdate
)
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from db.entity.user_entity import User as UserEntity
from db.entity.llm_endpoint_entity import (
    LLMEndpoint as LLMEndpointEntity,
    LLMEndpointGroup as LLMEndpointGroupEntity,
    LLMLevelEndpoint as LLMLevelEndpointEntity,
)


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


from uuid import uuid4


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> UserEntity:
    """Create a test user for foreign key relationships."""
    unique_id = str(uuid4())[:8]
    user = UserEntity(
        username=f"llm_ep_test_{unique_id}",
        email=f"llm_ep_test_{unique_id}@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def clean_llm_endpoints(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean LLM endpoint related tables before and after tests."""
    # Clean in correct order (level_endpoints first due to FK constraints)
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


class TestLLMEndpointDAOCreate:
    """Test create operations for LLMEndpointDAO."""
    
    async def test_create_endpoint_with_minimal_fields(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test creating an endpoint with only required fields."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Test Endpoint",
            base_url="https://api.example.com/v1",
            api_key_encrypted="encrypted_key_123",
            model_name="gpt-4",
        )
        
        created_endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        assert created_endpoint is not None
        assert created_endpoint.id is not None
        assert isinstance(created_endpoint.id, UUID)
        assert created_endpoint.user_id == test_user.id
        assert created_endpoint.name == "Test Endpoint"
        assert created_endpoint.base_url == "https://api.example.com/v1"
        assert created_endpoint.model_name == "gpt-4"
        assert created_endpoint.is_active is True  # Default value
        assert created_endpoint.failure_count == 0  # Default value
        assert created_endpoint.created_at is not None
        assert created_endpoint.updated_at is not None
    
    async def test_create_endpoint_with_all_fields(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test creating an endpoint with all fields specified."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Full Endpoint",
            base_url="https://api.full.com/v1",
            api_key_encrypted="encrypted_full_key",
            model_name="claude-3-opus",
            config_json={"temperature": 0.7, "max_tokens": 4096},
            is_active=False,
        )
        
        created_endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        assert created_endpoint is not None
        assert created_endpoint.name == "Full Endpoint"
        assert created_endpoint.config_json == {"temperature": 0.7, "max_tokens": 4096}
        assert created_endpoint.is_active is False
    
    async def test_create_endpoint_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test that create returns an LLMEndpoint DTO."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="DTO Test",
            base_url="https://dto.example.com",
            api_key_encrypted="dto_key",
            model_name="gpt-3.5-turbo",
        )
        
        created_endpoint = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        assert isinstance(created_endpoint, LLMEndpoint)


class TestLLMEndpointDAOGetById:
    """Test get_by_id operations for LLMEndpointDAO."""
    
    async def test_get_by_id_returns_endpoint(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test retrieving an endpoint by ID."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Get Test",
            base_url="https://get.example.com",
            api_key_encrypted="get_key",
            model_name="gpt-4",
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        fetched = await LLMEndpointDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Get Test"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        result = await LLMEndpointDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test that get_by_id returns an LLMEndpoint DTO."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="DTO Get Test",
            base_url="https://dtoget.example.com",
            api_key_encrypted="dto_get_key",
            model_name="gpt-4",
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        fetched = await LLMEndpointDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, LLMEndpoint)


class TestLLMEndpointDAOGetByUserId:
    """Test get_by_user_id operations for LLMEndpointDAO."""
    
    async def test_get_by_user_id_returns_endpoints(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test retrieving endpoints by user ID."""
        for i in range(3):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"User Endpoint {i}",
                base_url=f"https://user{i}.example.com",
                api_key_encrypted=f"user_key_{i}",
                model_name="gpt-4",
            )
            await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        endpoints = await LLMEndpointDAO.get_by_user_id(test_user.id, session=db_session)
        
        assert len(endpoints) == 3
        for ep in endpoints:
            assert ep.user_id == test_user.id
    
    async def test_get_by_user_id_empty_returns_empty_list(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that get_by_user_id returns empty list for user with no endpoints."""
        from uuid import uuid4
        
        endpoints = await LLMEndpointDAO.get_by_user_id(uuid4(), session=db_session)
        
        assert endpoints == []


class TestLLMEndpointDAOGetAll:
    """Test get_all operations for LLMEndpointDAO."""
    
    async def test_get_all_returns_all_endpoints(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test retrieving all endpoints."""
        for i in range(3):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"All Endpoint {i}",
                base_url=f"https://all{i}.example.com",
                api_key_encrypted=f"all_key_{i}",
                model_name="gpt-4",
            )
            await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        endpoints = await LLMEndpointDAO.get_all(session=db_session)
        
        assert len(endpoints) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that get_all returns empty list when no endpoints exist."""
        endpoints = await LLMEndpointDAO.get_all(session=db_session)
        
        assert endpoints == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
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
            await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        # Test limit
        endpoints_limited = await LLMEndpointDAO.get_all(limit=2, session=db_session)
        assert len(endpoints_limited) == 2
        
        # Test offset
        endpoints_offset = await LLMEndpointDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(endpoints_offset) == 2
    
    async def test_get_all_with_active_filter(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test get_all with active_only filter."""
        # Create active endpoint
        active_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Active Endpoint",
            base_url="https://active.example.com",
            api_key_encrypted="active_key",
            model_name="gpt-4",
            is_active=True,
        )
        await LLMEndpointDAO.create(active_create, session=db_session)
        
        # Create inactive endpoint
        inactive_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Inactive Endpoint",
            base_url="https://inactive.example.com",
            api_key_encrypted="inactive_key",
            model_name="gpt-4",
            is_active=False,
        )
        await LLMEndpointDAO.create(inactive_create, session=db_session)
        
        # Get all active
        active_endpoints = await LLMEndpointDAO.get_all(active_only=True, session=db_session)
        assert len(active_endpoints) == 1
        assert active_endpoints[0].name == "Active Endpoint"
        
        # Get all
        all_endpoints = await LLMEndpointDAO.get_all(active_only=False, session=db_session)
        assert len(all_endpoints) == 2


class TestLLMEndpointDAOUpdate:
    """Test update operations for LLMEndpointDAO."""
    
    async def test_update_endpoint_name(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test updating an endpoint's name."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Before Update",
            base_url="https://update.example.com",
            api_key_encrypted="update_key",
            model_name="gpt-4",
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        await asyncio.sleep(0.01)
        
        endpoint_update = LLMEndpointUpdate(
            id=created.id,
            name="After Update",
        )
        updated = await LLMEndpointDAO.update(endpoint_update, session=db_session)
        
        assert updated is not None
        assert updated.name == "After Update"
        assert updated.updated_at > created.updated_at
    
    async def test_update_endpoint_is_active(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test updating an endpoint's active status."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Active Test",
            base_url="https://activeupdate.example.com",
            api_key_encrypted="active_update_key",
            model_name="gpt-4",
            is_active=True,
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        endpoint_update = LLMEndpointUpdate(
            id=created.id,
            is_active=False,
        )
        updated = await LLMEndpointDAO.update(endpoint_update, session=db_session)
        
        assert updated is not None
        assert updated.is_active is False
    
    async def test_update_endpoint_config_json(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test updating an endpoint's config_json."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Config Test",
            base_url="https://config.example.com",
            api_key_encrypted="config_key",
            model_name="gpt-4",
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        new_config = {"temperature": 0.5, "max_tokens": 2048, "top_p": 0.9}
        endpoint_update = LLMEndpointUpdate(
            id=created.id,
            config_json=new_config,
        )
        updated = await LLMEndpointDAO.update(endpoint_update, session=db_session)
        
        assert updated is not None
        assert updated.config_json == new_config
    
    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that updating a nonexistent endpoint returns None."""
        from uuid import uuid4
        
        endpoint_update = LLMEndpointUpdate(
            id=uuid4(),
            name="Nonexistent",
        )
        
        result = await LLMEndpointDAO.update(endpoint_update, session=db_session)
        
        assert result is None


class TestLLMEndpointDAODelete:
    """Test delete operations for LLMEndpointDAO."""
    
    async def test_delete_existing_endpoint(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test deleting an existing endpoint."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Delete Test",
            base_url="https://delete.example.com",
            api_key_encrypted="delete_key",
            model_name="gpt-4",
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        result = await LLMEndpointDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify deleted
        fetched = await LLMEndpointDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that deleting a nonexistent endpoint returns False."""
        from uuid import uuid4
        
        result = await LLMEndpointDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestLLMEndpointDAOExists:
    """Test exists operations for LLMEndpointDAO."""
    
    async def test_exists_returns_true_for_existing(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test that exists returns True for existing endpoint."""
        endpoint_create = LLMEndpointCreate(
            user_id=test_user.id,
            name="Exists Test",
            base_url="https://exists.example.com",
            api_key_encrypted="exists_key",
            model_name="gpt-4",
        )
        created = await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        result = await LLMEndpointDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that exists returns False for nonexistent endpoint."""
        from uuid import uuid4
        
        result = await LLMEndpointDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestLLMEndpointDAOCount:
    """Test count operations for LLMEndpointDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, test_user: UserEntity, clean_llm_endpoints: None
    ):
        """Test that count returns the correct number of endpoints."""
        for i in range(3):
            endpoint_create = LLMEndpointCreate(
                user_id=test_user.id,
                name=f"Count Endpoint {i}",
                base_url=f"https://count{i}.example.com",
                api_key_encrypted=f"count_key_{i}",
                model_name="gpt-4",
            )
            await LLMEndpointDAO.create(endpoint_create, session=db_session)
        
        count = await LLMEndpointDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_returns_zero(
        self, db_session: AsyncSession, clean_llm_endpoints: None
    ):
        """Test that count returns 0 for empty table."""
        count = await LLMEndpointDAO.count(session=db_session)
        
        assert count == 0