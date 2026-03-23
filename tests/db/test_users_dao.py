# pyright: reportMissingImports=false
"""
Tests for UserDAO database operations.

This module tests CRUD operations for UserDAO following the DAO pattern.
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
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.user_dto import UserCreate, User, UserUpdate
from db.dao.user_dao import UserDAO
from db.entity.user_entity import User as UserEntity, APIKey as APIKeyEntity


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
async def clean_users_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


class TestUserDAOCreate:
    """Test create operations for UserDAO."""
    
    async def test_create_user_with_minimal_fields(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test creating a user with only required fields."""
        user_create = UserCreate(
            username="testuser",
            email="test@example.com",
        )
        
        created_user = await UserDAO.create(user_create, session=db_session)
        
        assert created_user is not None
        assert created_user.id is not None
        assert isinstance(created_user.id, UUID)
        assert created_user.username == "testuser"
        assert created_user.email == "test@example.com"
        assert created_user.is_active is True  # Default value
        assert created_user.created_at is not None
        assert created_user.updated_at is not None
        assert isinstance(created_user.created_at, datetime)
        assert isinstance(created_user.updated_at, datetime)
    
    async def test_create_user_with_all_fields(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test creating a user with all fields specified."""
        user_create = UserCreate(
            username="fulluser",
            email="full@example.com",
            is_active=False,
        )
        
        created_user = await UserDAO.create(user_create, session=db_session)
        
        assert created_user is not None
        assert created_user.username == "fulluser"
        assert created_user.email == "full@example.com"
        assert created_user.is_active is False
    
    async def test_create_user_returns_dto(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that create returns a User DTO, not an entity."""
        user_create = UserCreate(
            username="dtouser",
            email="dto@example.com",
        )
        
        created_user = await UserDAO.create(user_create, session=db_session)
        
        assert isinstance(created_user, User)
    
    async def test_create_duplicate_username_raises_error(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that duplicate usernames raise IntegrityError."""
        user_create1 = UserCreate(
            username="duplicateuser",
            email="user1@example.com",
        )
        user_create2 = UserCreate(
            username="duplicateuser",
            email="user2@example.com",
        )
        
        await UserDAO.create(user_create1, session=db_session)
        
        with pytest.raises(Exception):  # IntegrityError
            await UserDAO.create(user_create2, session=db_session)
    
    async def test_create_duplicate_email_raises_error(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that duplicate emails raise IntegrityError."""
        user_create1 = UserCreate(
            username="emailuser1",
            email="duplicate@example.com",
        )
        user_create2 = UserCreate(
            username="emailuser2",
            email="duplicate@example.com",
        )
        
        await UserDAO.create(user_create1, session=db_session)
        
        with pytest.raises(Exception):  # IntegrityError
            await UserDAO.create(user_create2, session=db_session)


class TestUserDAOGetById:
    """Test get_by_id operations for UserDAO."""
    
    async def test_get_by_id_returns_user(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test retrieving a user by ID."""
        user_create = UserCreate(
            username="getuser",
            email="get@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        fetched_user = await UserDAO.get_by_id(created_user.id, session=db_session)
        
        assert fetched_user is not None
        assert fetched_user.id == created_user.id
        assert fetched_user.username == "getuser"
        assert fetched_user.email == "get@example.com"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        nonexistent_id = uuid4()
        
        result = await UserDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that get_by_id returns a User DTO."""
        user_create = UserCreate(
            username="dtotest",
            email="dtotest@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        fetched_user = await UserDAO.get_by_id(created_user.id, session=db_session)
        
        assert isinstance(fetched_user, User)


class TestUserDAOGetByEmail:
    """Test get_by_email operations for UserDAO."""
    
    async def test_get_by_email_returns_user(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test retrieving a user by email."""
        user_create = UserCreate(
            username="emailtest",
            email="emailtest@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        fetched_user = await UserDAO.get_by_email("emailtest@example.com", session=db_session)
        
        assert fetched_user is not None
        assert fetched_user.id == created_user.id
        assert fetched_user.email == "emailtest@example.com"
    
    async def test_get_by_email_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that get_by_email returns None for nonexistent email."""
        result = await UserDAO.get_by_email("nonexistent@example.com", session=db_session)
        
        assert result is None
    
    async def test_get_by_email_is_case_sensitive(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that email lookup is case-sensitive (PostgreSQL default)."""
        user_create = UserCreate(
            username="casetest",
            email="Case@Test.com",
        )
        await UserDAO.create(user_create, session=db_session)
        
        # Should find with exact case
        fetched = await UserDAO.get_by_email("Case@Test.com", session=db_session)
        assert fetched is not None
        
        # Should not find with different case
        fetched_lower = await UserDAO.get_by_email("case@test.com", session=db_session)
        assert fetched_lower is None


class TestUserDAOGetAll:
    """Test get_all operations for UserDAO."""
    
    async def test_get_all_returns_all_users(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test retrieving all users."""
        for i in range(3):
            user_create = UserCreate(
                username=f"alluser{i}",
                email=f"alluser{i}@example.com",
            )
            await UserDAO.create(user_create, session=db_session)
        
        users = await UserDAO.get_all(session=db_session)
        
        assert len(users) == 3
        usernames = {u.username for u in users}
        assert usernames == {"alluser0", "alluser1", "alluser2"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that get_all returns empty list when no users exist."""
        users = await UserDAO.get_all(session=db_session)
        
        assert users == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            user_create = UserCreate(
                username=f"pageuser{i}",
                email=f"pageuser{i}@example.com",
            )
            await UserDAO.create(user_create, session=db_session)
        
        # Test limit
        users_limited = await UserDAO.get_all(limit=2, session=db_session)
        assert len(users_limited) == 2
        
        # Test offset
        users_offset = await UserDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(users_offset) == 2
        
        # Verify different users returned
        ids_limited = {u.id for u in users_limited}
        ids_offset = {u.id for u in users_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that get_all returns User DTOs."""
        user_create = UserCreate(
            username="dtolist",
            email="dtolist@example.com",
        )
        await UserDAO.create(user_create, session=db_session)
        
        users = await UserDAO.get_all(session=db_session)
        
        assert len(users) == 1
        assert isinstance(users[0], User)


class TestUserDAOUpdate:
    """Test update operations for UserDAO."""
    
    async def test_update_user_username(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test updating a user's username."""
        user_create = UserCreate(
            username="beforeupdate",
            email="update@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        # Wait a tiny bit to ensure timestamp changes
        await asyncio.sleep(0.01)
        
        user_update = UserUpdate(
            id=created_user.id,
            username="afterupdate",
        )
        updated_user = await UserDAO.update(user_update, session=db_session)
        
        assert updated_user is not None
        assert updated_user.username == "afterupdate"
        assert updated_user.email == "update@example.com"
        assert updated_user.updated_at > created_user.updated_at
    
    async def test_update_user_email(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test updating a user's email."""
        user_create = UserCreate(
            username="emailupdate",
            email="before@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        user_update = UserUpdate(
            id=created_user.id,
            email="after@example.com",
        )
        updated_user = await UserDAO.update(user_update, session=db_session)
        
        assert updated_user is not None
        assert updated_user.email == "after@example.com"
    
    async def test_update_user_is_active(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test updating a user's is_active status."""
        user_create = UserCreate(
            username="activetest",
            email="active@example.com",
            is_active=True,
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        user_update = UserUpdate(
            id=created_user.id,
            is_active=False,
        )
        updated_user = await UserDAO.update(user_update, session=db_session)
        
        assert updated_user is not None
        assert updated_user.is_active is False
    
    async def test_update_nonexistent_user_returns_none(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that updating a nonexistent user returns None."""
        from uuid import uuid4
        
        user_update = UserUpdate(
            id=uuid4(),
            username="nonexistent",
        )
        
        result = await UserDAO.update(user_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that update returns a User DTO."""
        user_create = UserCreate(
            username="dtoupdate",
            email="dtoupdate@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        user_update = UserUpdate(
            id=created_user.id,
            username="updateddto",
        )
        updated_user = await UserDAO.update(user_update, session=db_session)
        
        assert isinstance(updated_user, User)


class TestUserDAODelete:
    """Test delete operations for UserDAO."""
    
    async def test_delete_existing_user(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test deleting an existing user."""
        user_create = UserCreate(
            username="deleteuser",
            email="delete@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        result = await UserDAO.delete(created_user.id, session=db_session)
        
        assert result is True
        
        # Verify user is deleted
        fetched = await UserDAO.get_by_id(created_user.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_user_returns_false(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that deleting a nonexistent user returns False."""
        from uuid import uuid4
        
        result = await UserDAO.delete(uuid4(), session=db_session)
        
        assert result is False
    
    async def test_delete_cascades_to_api_keys(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that deleting a user cascades to API keys."""
        # Create user
        user_create = UserCreate(
            username="cascadetest",
            email="cascade@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        # Create API key for user (directly using entity since APIKeyDAO not tested here)
        api_key = APIKeyEntity(
            user_id=created_user.id,
            key_hash="sha256:cascade_hash",
        )
        db_session.add(api_key)
        await db_session.commit()
        await db_session.refresh(api_key)
        api_key_id = api_key.id
        
        # Delete user
        await UserDAO.delete(created_user.id, session=db_session)
        
        # Verify API key is also deleted
        from sqlalchemy import select
        result = await db_session.execute(
            select(APIKeyEntity).where(APIKeyEntity.id == api_key_id)
        )
        assert result.scalar_one_or_none() is None


class TestUserDAOExists:
    """Test exists operations for UserDAO."""
    
    async def test_exists_returns_true_for_existing_user(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that exists returns True for existing user."""
        user_create = UserCreate(
            username="existstest",
            email="exists@example.com",
        )
        created_user = await UserDAO.create(user_create, session=db_session)
        
        result = await UserDAO.exists(created_user.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_user(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that exists returns False for nonexistent user."""
        from uuid import uuid4
        
        result = await UserDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestUserDAOCount:
    """Test count operations for UserDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that count returns the correct number of users."""
        for i in range(3):
            user_create = UserCreate(
                username=f"countuser{i}",
                email=f"countuser{i}@example.com",
            )
            await UserDAO.create(user_create, session=db_session)
        
        count = await UserDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_users_table: None
    ):
        """Test that count returns 0 for empty table."""
        count = await UserDAO.count(session=db_session)
        
        assert count == 0