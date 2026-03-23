# pyright: reportMissingImports=false
"""
Tests for ToolDAO database operations.

This module tests CRUD operations for ToolDAO following the DAO pattern.
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
from db.dto.tool_dto import ToolCreate, Tool, ToolUpdate
from db.dao.tool_dao import ToolDAO
from db.entity.tool_entity import Tool as ToolEntity


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
async def clean_tools_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    await db_session.execute(delete(ToolEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(ToolEntity))
    await db_session.commit()


class TestToolDAOCreate:
    """Test create operations for ToolDAO."""
    
    async def test_create_tool_with_minimal_fields(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test creating a tool with only required fields."""
        tool_create = ToolCreate(
            name="test_tool",
        )
        
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        assert created_tool is not None
        assert created_tool.id is not None
        assert isinstance(created_tool.id, UUID)
        assert created_tool.name == "test_tool"
        assert created_tool.description is None
        assert created_tool.is_active is True  # Default value
        assert created_tool.created_at is not None
        assert created_tool.updated_at is not None
        assert isinstance(created_tool.created_at, datetime)
        assert isinstance(created_tool.updated_at, datetime)
    
    async def test_create_tool_with_all_fields(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test creating a tool with all fields specified."""
        tool_create = ToolCreate(
            name="full_tool",
            description="A comprehensive tool for testing",
            is_active=False,
        )
        
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        assert created_tool is not None
        assert created_tool.name == "full_tool"
        assert created_tool.description == "A comprehensive tool for testing"
        assert created_tool.is_active is False
    
    async def test_create_tool_returns_dto(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that create returns a Tool DTO, not an entity."""
        tool_create = ToolCreate(
            name="dto_tool",
        )
        
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        assert isinstance(created_tool, Tool)
    
    async def test_create_duplicate_name_raises_error(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that duplicate names raise IntegrityError."""
        tool_create1 = ToolCreate(name="duplicate_tool")
        tool_create2 = ToolCreate(name="duplicate_tool")
        
        await ToolDAO.create(tool_create1, session=db_session)
        
        with pytest.raises(Exception):  # IntegrityError
            await ToolDAO.create(tool_create2, session=db_session)


class TestToolDAOGetById:
    """Test get_by_id operations for ToolDAO."""
    
    async def test_get_by_id_returns_tool(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test retrieving a tool by ID."""
        tool_create = ToolCreate(
            name="get_tool",
            description="Tool for get test",
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        fetched_tool = await ToolDAO.get_by_id(created_tool.id, session=db_session)
        
        assert fetched_tool is not None
        assert fetched_tool.id == created_tool.id
        assert fetched_tool.name == "get_tool"
        assert fetched_tool.description == "Tool for get test"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        nonexistent_id = uuid4()
        
        result = await ToolDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that get_by_id returns a Tool DTO."""
        tool_create = ToolCreate(
            name="dto_get_test",
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        fetched_tool = await ToolDAO.get_by_id(created_tool.id, session=db_session)
        
        assert isinstance(fetched_tool, Tool)


class TestToolDAOGetByName:
    """Test get_by_name operations for ToolDAO."""
    
    async def test_get_by_name_returns_tool(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test retrieving a tool by name."""
        tool_create = ToolCreate(
            name="name_lookup_tool",
            description="Tool for name lookup test",
        )
        await ToolDAO.create(tool_create, session=db_session)
        
        fetched_tool = await ToolDAO.get_by_name("name_lookup_tool", session=db_session)
        
        assert fetched_tool is not None
        assert fetched_tool.name == "name_lookup_tool"
        assert fetched_tool.description == "Tool for name lookup test"
    
    async def test_get_by_name_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that get_by_name returns None for nonexistent name."""
        result = await ToolDAO.get_by_name("nonexistent_tool", session=db_session)
        
        assert result is None


class TestToolDAOGetAll:
    """Test get_all operations for ToolDAO."""
    
    async def test_get_all_returns_all_tools(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test retrieving all tools."""
        for i in range(3):
            tool_create = ToolCreate(
                name=f"all_tool_{i}",
                description=f"Tool number {i}",
            )
            await ToolDAO.create(tool_create, session=db_session)
        
        tools = await ToolDAO.get_all(session=db_session)
        
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"all_tool_0", "all_tool_1", "all_tool_2"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that get_all returns empty list when no tools exist."""
        tools = await ToolDAO.get_all(session=db_session)
        
        assert tools == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            tool_create = ToolCreate(
                name=f"page_tool_{i}",
            )
            await ToolDAO.create(tool_create, session=db_session)
        
        # Test limit
        tools_limited = await ToolDAO.get_all(limit=2, session=db_session)
        assert len(tools_limited) == 2
        
        # Test offset
        tools_offset = await ToolDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(tools_offset) == 2
        
        # Verify different tools returned
        ids_limited = {t.id for t in tools_limited}
        ids_offset = {t.id for t in tools_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that get_all returns Tool DTOs."""
        tool_create = ToolCreate(
            name="dto_list_tool",
        )
        await ToolDAO.create(tool_create, session=db_session)
        
        tools = await ToolDAO.get_all(session=db_session)
        
        assert len(tools) == 1
        assert isinstance(tools[0], Tool)


class TestToolDAOGetActive:
    """Test get_active operations for ToolDAO."""
    
    async def test_get_active_returns_only_active_tools(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that get_active returns only active tools."""
        # Create active tools
        tool_create1 = ToolCreate(name="active_tool_1", is_active=True)
        tool_create2 = ToolCreate(name="active_tool_2", is_active=True)
        await ToolDAO.create(tool_create1, session=db_session)
        await ToolDAO.create(tool_create2, session=db_session)
        
        # Create inactive tool
        tool_create3 = ToolCreate(name="inactive_tool", is_active=False)
        await ToolDAO.create(tool_create3, session=db_session)
        
        active_tools = await ToolDAO.get_active(session=db_session)
        
        assert len(active_tools) == 2
        names = {t.name for t in active_tools}
        assert names == {"active_tool_1", "active_tool_2"}


class TestToolDAOUpdate:
    """Test update operations for ToolDAO."""
    
    async def test_update_tool_name(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test updating a tool's name."""
        tool_create = ToolCreate(
            name="before_update",
            description="Original description",
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        # Wait a tiny bit to ensure timestamp changes
        await asyncio.sleep(0.01)
        
        tool_update = ToolUpdate(
            id=created_tool.id,
            name="after_update",
        )
        updated_tool = await ToolDAO.update(tool_update, session=db_session)
        
        assert updated_tool is not None
        assert updated_tool.name == "after_update"
        assert updated_tool.description == "Original description"
        assert updated_tool.updated_at > created_tool.updated_at
    
    async def test_update_tool_description(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test updating a tool's description."""
        tool_create = ToolCreate(
            name="description_update",
            description="Before update",
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        tool_update = ToolUpdate(
            id=created_tool.id,
            description="After update",
        )
        updated_tool = await ToolDAO.update(tool_update, session=db_session)
        
        assert updated_tool is not None
        assert updated_tool.description == "After update"
    
    async def test_update_tool_is_active(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test updating a tool's is_active status."""
        tool_create = ToolCreate(
            name="active_update",
            is_active=True,
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        tool_update = ToolUpdate(
            id=created_tool.id,
            is_active=False,
        )
        updated_tool = await ToolDAO.update(tool_update, session=db_session)
        
        assert updated_tool is not None
        assert updated_tool.is_active is False
    
    async def test_update_nonexistent_tool_returns_none(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that updating a nonexistent tool returns None."""
        from uuid import uuid4
        
        tool_update = ToolUpdate(
            id=uuid4(),
            name="nonexistent",
        )
        
        result = await ToolDAO.update(tool_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that update returns a Tool DTO."""
        tool_create = ToolCreate(
            name="dto_update",
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        tool_update = ToolUpdate(
            id=created_tool.id,
            name="updated_dto",
        )
        updated_tool = await ToolDAO.update(tool_update, session=db_session)
        
        assert isinstance(updated_tool, Tool)


class TestToolDAODelete:
    """Test delete operations for ToolDAO."""
    
    async def test_delete_existing_tool(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test deleting an existing tool."""
        tool_create = ToolCreate(
            name="delete_tool",
        )
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        result = await ToolDAO.delete(created_tool.id, session=db_session)
        
        assert result is True
        
        # Verify tool is deleted
        fetched = await ToolDAO.get_by_id(created_tool.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_tool_returns_false(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that deleting a nonexistent tool returns False."""
        from uuid import uuid4
        
        result = await ToolDAO.delete(uuid4(), session=db_session)
        
        assert result is False
    
    async def test_delete_cascades_to_versions(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that deleting a tool cascades to tool versions."""
        from db.entity.tool_entity import ToolVersion as ToolVersionEntity
        from db.dao.tool_version_dao import ToolVersionDAO
        from db.dto.tool_dto import ToolVersionCreate
        
        # Create tool
        tool_create = ToolCreate(name="cascade_tool")
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        # Create version
        version_create = ToolVersionCreate(
            tool_id=created_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        # Delete tool
        await ToolDAO.delete(created_tool.id, session=db_session)
        
        # Verify version is also deleted
        from sqlalchemy import select
        result = await db_session.execute(
            select(ToolVersionEntity).where(ToolVersionEntity.id == created_version.id)
        )
        assert result.scalar_one_or_none() is None


class TestToolDAOExists:
    """Test exists operations for ToolDAO."""
    
    async def test_exists_returns_true_for_existing_tool(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that exists returns True for existing tool."""
        tool_create = ToolCreate(name="exists_tool")
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        result = await ToolDAO.exists(created_tool.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_tool(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that exists returns False for nonexistent tool."""
        from uuid import uuid4
        
        result = await ToolDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestToolDAOCount:
    """Test count operations for ToolDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that count returns the correct number of tools."""
        for i in range(3):
            tool_create = ToolCreate(name=f"count_tool_{i}")
            await ToolDAO.create(tool_create, session=db_session)
        
        count = await ToolDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_tools_table: None
    ):
        """Test that count returns 0 for empty table."""
        count = await ToolDAO.count(session=db_session)
        
        assert count == 0