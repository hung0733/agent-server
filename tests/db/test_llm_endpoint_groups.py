# pyright: reportMissingImports=false
"""
Tests for LLM endpoint group database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, default uniqueness behavior, and cascading deletion
for llm_endpoint_groups table.
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
from db.schema.llm_endpoints import LLMEndpointGroup
from db.schema.users import User  # noqa: F401 - Import for relationship resolution
from db.schema.agents import AgentInstance  # noqa: F401 - Import for relationship resolution
from db.types import gen_random_uuid


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
        
        # Create llm_endpoint_groups table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_endpoint_groups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (name, user_id)
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_llm_endpoint_groups_user 
            ON llm_endpoint_groups(user_id)
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_endpoint_groups_default 
            ON llm_endpoint_groups(user_id) 
            WHERE is_default = true
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS llm_endpoint_groups"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()


class TestLLMEndpointGroupSchema:
    """Test llm_endpoint_groups schema creation and structure."""
    
    async def test_llm_endpoint_groups_table_exists(self, db_session: AsyncSession):
        """Test that the llm_endpoint_groups table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'llm_endpoint_groups'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "llm_endpoint_groups"
    
    async def test_llm_endpoint_groups_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in llm_endpoint_groups table."""
        expected_columns = {
            'id', 'user_id', 'name', 'description', 'is_default',
            'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'llm_endpoint_groups'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_llm_endpoint_groups_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'llm_endpoint_groups'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_llm_endpoint_groups_user' in indexes
        assert 'idx_llm_endpoint_groups_default' in indexes


class TestLLMEndpointGroupCRUD:
    """Test CRUD operations for LLMEndpointGroup model."""
    
    async def test_create_endpoint_group_minimal(self, db_session: AsyncSession):
        """Test creating an endpoint group with minimal fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        endpoint_group = LLMEndpointGroup(
            user_id=user_id,
            name="Production LLMs",
        )
        db_session.add(endpoint_group)
        await db_session.commit()
        await db_session.refresh(endpoint_group)
        
        assert endpoint_group.id is not None
        assert isinstance(endpoint_group.id, UUID)
        assert endpoint_group.user_id == user_id
        assert endpoint_group.name == "Production LLMs"
        assert endpoint_group.description is None
        assert endpoint_group.is_default is False
        assert endpoint_group.created_at is not None
        assert endpoint_group.updated_at is not None
    
    async def test_create_endpoint_group_full(self, db_session: AsyncSession):
        """Test creating an endpoint group with all fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        endpoint_group = LLMEndpointGroup(
            user_id=user_id,
            name="Development LLMs",
            description="LLM endpoints for development and testing",
            is_default=True,
        )
        db_session.add(endpoint_group)
        await db_session.commit()
        await db_session.refresh(endpoint_group)
        
        assert endpoint_group.name == "Development LLMs"
        assert endpoint_group.description == "LLM endpoints for development and testing"
        assert endpoint_group.is_default is True
    
    async def test_update_endpoint_group(self, db_session: AsyncSession):
        """Test updating an endpoint group."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        endpoint_group = LLMEndpointGroup(
            user_id=user_id,
            name="Test Group",
        )
        db_session.add(endpoint_group)
        await db_session.commit()
        
        original_updated_at = endpoint_group.updated_at
        await asyncio.sleep(0.01)  # Ensure time difference
        
        endpoint_group.description = "Updated description"
        endpoint_group.is_default = True
        await db_session.commit()
        await db_session.refresh(endpoint_group)
        
        assert endpoint_group.description == "Updated description"
        assert endpoint_group.is_default is True
        assert endpoint_group.updated_at > original_updated_at
    
    async def test_delete_endpoint_group(self, db_session: AsyncSession):
        """Test deleting an endpoint group."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        endpoint_group = LLMEndpointGroup(
            user_id=user_id,
            name="Delete Test",
        )
        db_session.add(endpoint_group)
        await db_session.commit()
        
        await db_session.delete(endpoint_group)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.id == endpoint_group.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_get_endpoint_group_by_id(self, db_session: AsyncSession):
        """Test retrieving an endpoint group by ID."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        endpoint_group = LLMEndpointGroup(
            user_id=user_id,
            name="Get Test",
            description="Test for retrieval",
        )
        db_session.add(endpoint_group)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.id == endpoint_group.id)
        )
        fetched = result.scalar_one()
        
        assert fetched is not None
        assert fetched.id == endpoint_group.id
        assert fetched.name == "Get Test"
        assert fetched.description == "Test for retrieval"
    
    async def test_list_user_endpoint_groups(self, db_session: AsyncSession):
        """Test listing endpoint groups for a user."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create multiple endpoint groups
        for i in range(5):
            endpoint_group = LLMEndpointGroup(
                user_id=user_id,
                name=f"Group{i}",
                description=f"Test group {i}",
            )
            db_session.add(endpoint_group)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.user_id == user_id)
        )
        groups = result.scalars().all()
        
        assert len(groups) == 5
        assert all(g.user_id == user_id for g in groups)


class TestForeignKeys:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_user_id_enforced(self, db_session: AsyncSession):
        """Test that user_id FK constraint is enforced."""
        # Try to create endpoint group with non-existent user_id
        fake_user_id = uuid4()
        endpoint_group = LLMEndpointGroup(
            user_id=fake_user_id,
            name="Invalid Group",
        )
        db_session.add(endpoint_group)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_user(self, db_session: AsyncSession):
        """Test that deleting user cascades to endpoint groups."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create endpoint groups for this user
        for i in range(3):
            endpoint_group = LLMEndpointGroup(
                user_id=user_id,
                name=f"Group{i}",
            )
            db_session.add(endpoint_group)
        await db_session.commit()
        
        # Delete user
        await db_session.execute(text(f"""
            DELETE FROM users WHERE id = '{user_id}'
        """))
        await db_session.commit()
        
        # Verify endpoint groups are deleted
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.user_id == user_id)
        )
        groups = result.scalars().all()
        assert len(groups) == 0


class TestDefaultUniqueness:
    """Test the conditional unique constraint on is_default."""
    
    async def test_only_one_default_per_user(self, db_session: AsyncSession):
        """Test that only one endpoint group per user can be default."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create first default endpoint group
        group1 = LLMEndpointGroup(
            user_id=user_id,
            name="Default Group 1",
            is_default=True,
        )
        db_session.add(group1)
        await db_session.commit()
        
        # Try to create second default endpoint group - should fail
        group2 = LLMEndpointGroup(
            user_id=user_id,
            name="Default Group 2",
            is_default=True,
        )
        db_session.add(group2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_multiple_non_default_allowed(self, db_session: AsyncSession):
        """Test that multiple non-default groups are allowed per user."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create multiple non-default endpoint groups
        for i in range(5):
            endpoint_group = LLMEndpointGroup(
                user_id=user_id,
                name=f"Group{i}",
                is_default=False,
            )
            db_session.add(endpoint_group)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.user_id == user_id)
        )
        groups = result.scalars().all()
        
        assert len(groups) == 5
        assert all(not g.is_default for g in groups)
    
    async def test_default_per_different_users(self, db_session: AsyncSession):
        """Test that different users can each have their own default."""
        user1_id = gen_random_uuid()
        user2_id = gen_random_uuid()
        
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user1_id}', 'user1', 'user1@example.com')
        """))
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user2_id}', 'user2', 'user2@example.com')
        """))
        await db_session.commit()
        
        # Create default group for user1
        group1 = LLMEndpointGroup(
            user_id=user1_id,
            name="User1 Default",
            is_default=True,
        )
        db_session.add(group1)
        
        # Create default group for user2
        group2 = LLMEndpointGroup(
            user_id=user2_id,
            name="User2 Default",
            is_default=True,
        )
        db_session.add(group2)
        
        await db_session.commit()
        
        # Verify both defaults exist
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.is_default == True)
        )
        defaults = result.scalars().all()
        
        assert len(defaults) == 2
        assert any(g.user_id == user1_id for g in defaults)
        assert any(g.user_id == user2_id for g in defaults)
    
    async def test_change_default_group(self, db_session: AsyncSession):
        """Test changing which group is the default."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create two endpoint groups
        group1 = LLMEndpointGroup(
            user_id=user_id,
            name="Group 1",
            is_default=True,
        )
        group2 = LLMEndpointGroup(
            user_id=user_id,
            name="Group 2",
            is_default=False,
        )
        db_session.add(group1)
        db_session.add(group2)
        await db_session.commit()
        
        # Unset default from group1
        group1.is_default = False
        await db_session.commit()
        
        # Now set default on group2
        group2.is_default = True
        await db_session.commit()
        
        # Verify group2 is now the default
        result = await db_session.execute(
            select(LLMEndpointGroup)
            .where(LLMEndpointGroup.user_id == user_id)
            .where(LLMEndpointGroup.is_default == True)
        )
        default_group = result.scalar_one()
        assert default_group.id == group2.id


class TestUniqueNamePerUser:
    """Test the unique constraint on name per user."""
    
    async def test_unique_name_per_user(self, db_session: AsyncSession):
        """Test that group names must be unique per user."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        # Create first endpoint group
        group1 = LLMEndpointGroup(
            user_id=user_id,
            name="My Group",
        )
        db_session.add(group1)
        await db_session.commit()
        
        # Try to create another group with same name for same user
        group2 = LLMEndpointGroup(
            user_id=user_id,
            name="My Group",
        )
        db_session.add(group2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_same_name_different_users(self, db_session: AsyncSession):
        """Test that different users can have groups with same name."""
        user1_id = gen_random_uuid()
        user2_id = gen_random_uuid()
        
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user1_id}', 'user1', 'user1@example.com')
        """))
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user2_id}', 'user2', 'user2@example.com')
        """))
        await db_session.commit()
        
        # Create group with same name for both users
        group1 = LLMEndpointGroup(
            user_id=user1_id,
            name="My Group",
        )
        group2 = LLMEndpointGroup(
            user_id=user2_id,
            name="My Group",
        )
        db_session.add(group1)
        db_session.add(group2)
        
        # Should succeed - different users
        await db_session.commit()
        
        # Verify both groups exist
        result = await db_session.execute(
            select(LLMEndpointGroup).where(LLMEndpointGroup.name == "My Group")
        )
        groups = result.scalars().all()
        
        assert len(groups) == 2


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_endpoint_group_create_validation(self):
        """Test LLMEndpointGroupCreate model validation."""
        from db.models.llm_endpoint import LLMEndpointGroupCreate
        
        user_id = gen_random_uuid()
        
        # Valid creation
        data = {
            "user_id": user_id,
            "name": "Valid Group",
            "description": "A valid test group",
            "is_default": True,
        }
        model = LLMEndpointGroupCreate(**data)
        
        assert model.user_id == user_id
        assert model.name == "Valid Group"
        assert model.description == "A valid test group"
        assert model.is_default is True
    
    def test_endpoint_group_validation_minimal(self):
        """Test LLMEndpointGroupCreate with minimal fields."""
        from db.models.llm_endpoint import LLMEndpointGroupCreate
        
        user_id = gen_random_uuid()
        
        data = {
            "user_id": user_id,
            "name": "Minimal Group",
        }
        model = LLMEndpointGroupCreate(**data)
        
        assert model.user_id == user_id
        assert model.name == "Minimal Group"
        assert model.description is None
        assert model.is_default is False
    
    def test_endpoint_group_name_required(self):
        """Test that name is required in LLMEndpointGroupCreate."""
        from db.models.llm_endpoint import LLMEndpointGroupCreate
        from pydantic import ValidationError
        
        user_id = gen_random_uuid()
        
        # Missing name should fail
        with pytest.raises(ValidationError):
            LLMEndpointGroupCreate(
                user_id=user_id,
                # name is missing
            )
    
    def test_endpoint_group_full_model(self):
        """Test LLMEndpointGroup model with all fields."""
        from db.models.llm_endpoint import LLMEndpointGroup
        
        user_id = gen_random_uuid()
        group_id = gen_random_uuid()
        
        data = {
            "id": group_id,
            "user_id": user_id,
            "name": "Full Group",
            "description": "A complete test group",
            "is_default": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        model = LLMEndpointGroup(**data)
        
        assert model.id == group_id
        assert model.user_id == user_id
        assert model.name == "Full Group"
        assert model.description == "A complete test group"
        assert model.is_default is True
        assert model.created_at is not None
        assert model.updated_at is not None
