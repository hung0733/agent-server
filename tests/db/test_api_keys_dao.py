# pyright: reportMissingImports=false
"""
Tests for APIKeyDAO database operations.

This module tests CRUD operations for APIKeyDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.dto.user_dto import UserCreate, APIKeyCreate, APIKey, APIKeyUpdate
from db.dao.user_dao import UserDAO
from db.dao.api_key_dao import APIKeyDAO
from db.entity.user_entity import User as UserEntity, APIKey as APIKeyEntity


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
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
async def test_user(db_session: AsyncSession) -> dict:
    """Create a test user for API key tests.
    
    Returns a dict with the created user DTO.
    """
    user_create = UserCreate(
        username="apikeytestuser",
        email="apikeytestuser@example.com",
    )
    user = await UserDAO.create(user_create, session=db_session)
    return {"user": user}


@pytest_asyncio.fixture
async def clean_tables(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    await db_session.execute(delete(APIKeyEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(APIKeyEntity))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


class TestAPIKeyDAOCreate:
    """Test create operations for APIKeyDAO."""
    
    async def test_create_api_key_with_minimal_fields(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test creating an API key with only required fields."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:test_hash_value",
        )
        
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        assert created_key is not None
        assert created_key.id is not None
        assert isinstance(created_key.id, UUID)
        assert created_key.user_id == user.id
        assert created_key.key_hash == "sha256:test_hash_value"
        assert created_key.name is None
        assert created_key.is_active is True  # Default value
        assert created_key.last_used_at is None
        assert created_key.expires_at is None
        assert created_key.created_at is not None
        assert isinstance(created_key.created_at, datetime)
    
    async def test_create_api_key_with_all_fields(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test creating an API key with all fields specified."""
        user = test_user["user"]
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=30)
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:full_hash",
            name="Production Key",
            is_active=False,
            last_used_at=now,
            expires_at=expires,
        )
        
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        assert created_key is not None
        assert created_key.name == "Production Key"
        assert created_key.is_active is False
        assert created_key.last_used_at is not None
        assert created_key.expires_at is not None
    
    async def test_create_api_key_returns_dto(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that create returns an APIKey DTO."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:dto_test",
        )
        
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        assert isinstance(created_key, APIKey)
    
    async def test_create_api_key_invalid_user_raises_error(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that creating API key with invalid user_id raises error."""
        from uuid import uuid4
        
        api_key_create = APIKeyCreate(
            user_id=uuid4(),  # Non-existent user
            key_hash="sha256:invalid_user",
        )
        
        with pytest.raises(Exception):  # IntegrityError
            await APIKeyDAO.create(api_key_create, session=db_session)


class TestAPIKeyDAOGetById:
    """Test get_by_id operations for APIKeyDAO."""
    
    async def test_get_by_id_returns_api_key(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test retrieving an API key by ID."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:get_test",
            name="Test Key",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        fetched_key = await APIKeyDAO.get_by_id(created_key.id, session=db_session)
        
        assert fetched_key is not None
        assert fetched_key.id == created_key.id
        assert fetched_key.key_hash == "sha256:get_test"
        assert fetched_key.name == "Test Key"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        result = await APIKeyDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that get_by_id returns an APIKey DTO."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:dto_get",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        fetched_key = await APIKeyDAO.get_by_id(created_key.id, session=db_session)
        
        assert isinstance(fetched_key, APIKey)


class TestAPIKeyDAOGetByUserId:
    """Test get_by_user_id operations for APIKeyDAO."""
    
    async def test_get_by_user_id_returns_keys(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test retrieving all API keys for a user."""
        user = test_user["user"]
        
        # Create multiple API keys
        for i in range(3):
            api_key_create = APIKeyCreate(
                user_id=user.id,
                key_hash=f"sha256:user_keys_{i}",
                name=f"Key {i}",
            )
            await APIKeyDAO.create(api_key_create, session=db_session)
        
        keys = await APIKeyDAO.get_by_user_id(user.id, session=db_session)
        
        assert len(keys) == 3
        key_names = {k.name for k in keys}
        assert key_names == {"Key 0", "Key 1", "Key 2"}
    
    async def test_get_by_user_id_no_keys_returns_empty_list(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that get_by_user_id returns empty list when no keys exist."""
        user = test_user["user"]
        
        keys = await APIKeyDAO.get_by_user_id(user.id, session=db_session)
        
        assert keys == []
    
    async def test_get_by_user_id_nonexistent_user_returns_empty(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_by_user_id returns empty list for nonexistent user."""
        from uuid import uuid4
        
        keys = await APIKeyDAO.get_by_user_id(uuid4(), session=db_session)
        
        assert keys == []
    
    async def test_get_by_user_id_returns_dtos(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that get_by_user_id returns APIKey DTOs."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:dto_list",
        )
        await APIKeyDAO.create(api_key_create, session=db_session)
        
        keys = await APIKeyDAO.get_by_user_id(user.id, session=db_session)
        
        assert len(keys) == 1
        assert isinstance(keys[0], APIKey)


class TestAPIKeyDAOGetAll:
    """Test get_all operations for APIKeyDAO."""
    
    async def test_get_all_returns_all_keys(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test retrieving all API keys."""
        user = test_user["user"]
        
        for i in range(3):
            api_key_create = APIKeyCreate(
                user_id=user.id,
                key_hash=f"sha256:all_keys_{i}",
            )
            await APIKeyDAO.create(api_key_create, session=db_session)
        
        keys = await APIKeyDAO.get_all(session=db_session)
        
        assert len(keys) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_all returns empty list when no keys exist."""
        keys = await APIKeyDAO.get_all(session=db_session)
        
        assert keys == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test get_all with limit and offset."""
        user = test_user["user"]
        
        for i in range(5):
            api_key_create = APIKeyCreate(
                user_id=user.id,
                key_hash=f"sha256:page_keys_{i}",
            )
            await APIKeyDAO.create(api_key_create, session=db_session)
        
        # Test limit
        keys_limited = await APIKeyDAO.get_all(limit=2, session=db_session)
        assert len(keys_limited) == 2
        
        # Test offset
        keys_offset = await APIKeyDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(keys_offset) == 2
        
        # Verify different keys returned
        ids_limited = {k.id for k in keys_limited}
        ids_offset = {k.id for k in keys_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that get_all returns APIKey DTOs."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:dto_all",
        )
        await APIKeyDAO.create(api_key_create, session=db_session)
        
        keys = await APIKeyDAO.get_all(session=db_session)
        
        assert len(keys) == 1
        assert isinstance(keys[0], APIKey)


class TestAPIKeyDAOUpdate:
    """Test update operations for APIKeyDAO."""
    
    async def test_update_api_key_name(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test updating an API key's name."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:update_name",
            name="Original Name",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        # Wait a tiny bit to ensure timestamp changes
        await asyncio.sleep(0.01)
        
        api_key_update = APIKeyUpdate(
            id=created_key.id,
            name="Updated Name",
        )
        updated_key = await APIKeyDAO.update(api_key_update, session=db_session)
        
        assert updated_key is not None
        assert updated_key.name == "Updated Name"
        assert updated_key.key_hash == "sha256:update_name"
    
    async def test_update_api_key_last_used_at(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test updating last_used_at timestamp."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:last_used",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        assert created_key.last_used_at is None
        
        now = datetime.now(timezone.utc)
        api_key_update = APIKeyUpdate(
            id=created_key.id,
            last_used_at=now,
        )
        updated_key = await APIKeyDAO.update(api_key_update, session=db_session)
        
        assert updated_key is not None
        assert updated_key.last_used_at is not None
        assert isinstance(updated_key.last_used_at, datetime)
    
    async def test_update_api_key_is_active(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test deactivating an API key."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:deactivate",
            is_active=True,
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        assert created_key.is_active is True
        
        api_key_update = APIKeyUpdate(
            id=created_key.id,
            is_active=False,
        )
        updated_key = await APIKeyDAO.update(api_key_update, session=db_session)
        
        assert updated_key is not None
        assert updated_key.is_active is False
    
    async def test_update_api_key_expires_at(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test setting expiration date."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:expires",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        assert created_key.expires_at is None
        
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        api_key_update = APIKeyUpdate(
            id=created_key.id,
            expires_at=expires,
        )
        updated_key = await APIKeyDAO.update(api_key_update, session=db_session)
        
        assert updated_key is not None
        assert updated_key.expires_at is not None
    
    async def test_update_nonexistent_key_returns_none(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that updating a nonexistent key returns None."""
        from uuid import uuid4
        
        api_key_update = APIKeyUpdate(
            id=uuid4(),
            name="Nonexistent",
        )
        
        result = await APIKeyDAO.update(api_key_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that update returns an APIKey DTO."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:dto_update",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        api_key_update = APIKeyUpdate(
            id=created_key.id,
            name="Updated DTO",
        )
        updated_key = await APIKeyDAO.update(api_key_update, session=db_session)
        
        assert isinstance(updated_key, APIKey)


class TestAPIKeyDAODelete:
    """Test delete operations for APIKeyDAO."""
    
    async def test_delete_existing_key(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test deleting an existing API key."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:delete",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        result = await APIKeyDAO.delete(created_key.id, session=db_session)
        
        assert result is True
        
        # Verify key is deleted
        fetched = await APIKeyDAO.get_by_id(created_key.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_key_returns_false(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that deleting a nonexistent key returns False."""
        from uuid import uuid4
        
        result = await APIKeyDAO.delete(uuid4(), session=db_session)
        
        assert result is False
    
    async def test_delete_does_not_affect_user(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that deleting an API key does not delete the user."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:delete_no_user",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        await APIKeyDAO.delete(created_key.id, session=db_session)
        
        # User should still exist
        fetched_user = await UserDAO.get_by_id(user.id, session=db_session)
        assert fetched_user is not None


class TestAPIKeyDAOExists:
    """Test exists operations for APIKeyDAO."""
    
    async def test_exists_returns_true_for_existing_key(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that exists returns True for existing key."""
        user = test_user["user"]
        
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:exists",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        
        result = await APIKeyDAO.exists(created_key.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_key(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that exists returns False for nonexistent key."""
        from uuid import uuid4
        
        result = await APIKeyDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestAPIKeyDAOCount:
    """Test count operations for APIKeyDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that count returns the correct number of keys."""
        user = test_user["user"]
        
        for i in range(3):
            api_key_create = APIKeyCreate(
                user_id=user.id,
                key_hash=f"sha256:count_{i}",
            )
            await APIKeyDAO.create(api_key_create, session=db_session)
        
        count = await APIKeyDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that count returns 0 for empty table."""
        count = await APIKeyDAO.count(session=db_session)
        
        assert count == 0


class TestAPIKeyDAOGetActiveKeysForUser:
    """Test get_active_keys_for_user operations for APIKeyDAO."""
    
    async def test_get_active_keys_returns_only_active(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that only active keys are returned."""
        user = test_user["user"]
        
        # Create active key
        active_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:active",
            name="Active Key",
            is_active=True,
        )
        await APIKeyDAO.create(active_create, session=db_session)
        
        # Create inactive key
        inactive_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:inactive",
            name="Inactive Key",
            is_active=False,
        )
        await APIKeyDAO.create(inactive_create, session=db_session)
        
        active_keys = await APIKeyDAO.get_active_keys_for_user(user.id, session=db_session)
        
        assert len(active_keys) == 1
        assert active_keys[0].name == "Active Key"
        assert active_keys[0].is_active is True
    
    async def test_get_active_keys_no_active_returns_empty(
        self, db_session: AsyncSession, clean_tables: None, test_user: dict
    ):
        """Test that empty list is returned when no active keys exist."""
        user = test_user["user"]
        
        # Create only inactive key
        inactive_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:only_inactive",
            is_active=False,
        )
        await APIKeyDAO.create(inactive_create, session=db_session)
        
        active_keys = await APIKeyDAO.get_active_keys_for_user(user.id, session=db_session)
        
        assert active_keys == []


class TestAPIKeyRelationshipWithUser:
    """Test API key relationship with users (cascade delete, etc.)."""
    
    async def test_api_keys_deleted_when_user_deleted(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that API keys are cascade deleted when user is deleted."""
        # Create user
        user_create = UserCreate(
            username="cascadeuser",
            email="cascade@example.com",
        )
        user = await UserDAO.create(user_create, session=db_session)
        
        # Create API keys for user
        api_key_create = APIKeyCreate(
            user_id=user.id,
            key_hash="sha256:cascade",
        )
        created_key = await APIKeyDAO.create(api_key_create, session=db_session)
        key_id = created_key.id
        
        # Delete user
        await UserDAO.delete(user.id, session=db_session)
        
        # Verify API key is also deleted
        fetched_key = await APIKeyDAO.get_by_id(key_id, session=db_session)
        assert fetched_key is None