# pyright: reportMissingImports=false
"""
Tests for ToolVersionDAO database operations.

This module tests CRUD operations for ToolVersionDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.tool_dto import (
    ToolCreate,
    Tool,
    ToolVersionCreate,
    ToolVersion,
    ToolVersionUpdate,
)
from db.dao.tool_dao import ToolDAO
from db.dao.tool_version_dao import ToolVersionDAO
from db.entity.tool_entity import Tool as ToolEntity, ToolVersion as ToolVersionEntity


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
async def clean_tables(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean both tools and tool_versions tables."""
    await db_session.execute(delete(ToolVersionEntity))
    await db_session.execute(delete(ToolEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(ToolVersionEntity))
    await db_session.execute(delete(ToolEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def sample_tool(db_session: AsyncSession, clean_tables: None) -> Tool:
    """Create a sample tool for testing versions."""
    tool_create = ToolCreate(name="sample_tool")
    return await ToolDAO.create(tool_create, session=db_session)


class TestToolVersionDAOCreate:
    """Test create operations for ToolVersionDAO."""
    
    async def test_create_version_with_minimal_fields(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test creating a tool version with only required fields."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        assert created_version is not None
        assert created_version.id is not None
        assert isinstance(created_version.id, UUID)
        assert created_version.tool_id == sample_tool.id
        assert created_version.version == "1.0.0"
        assert created_version.input_schema is None
        assert created_version.output_schema is None
        assert created_version.implementation_ref is None
        assert created_version.config_json is None
        assert created_version.is_default is False
        assert created_version.created_at is not None
        assert isinstance(created_version.created_at, datetime)
    
    async def test_create_version_with_all_fields(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test creating a tool version with all fields specified."""
        input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        }
        output_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "object"}}
            },
        }
        config_json: dict[str, Any] = {
            "timeout": 30,
            "max_results": 10,
        }
        
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="2.0.0",
            input_schema=input_schema,
            output_schema=output_schema,
            implementation_ref="tools.web_search:search",
            config_json=config_json,
            is_default=True,
        )
        
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        assert created_version is not None
        assert created_version.version == "2.0.0"
        assert created_version.input_schema == input_schema
        assert created_version.output_schema == output_schema
        assert created_version.implementation_ref == "tools.web_search:search"
        assert created_version.config_json == config_json
        assert created_version.is_default is True
    
    async def test_create_version_returns_dto(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that create returns a ToolVersion DTO, not an entity."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        assert isinstance(created_version, ToolVersion)
    
    async def test_create_version_with_nonexistent_tool_raises_error(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that creating a version with nonexistent tool_id raises error."""
        from uuid import uuid4
        
        version_create = ToolVersionCreate(
            tool_id=uuid4(),
            version="1.0.0",
        )
        
        with pytest.raises(Exception):  # IntegrityError
            await ToolVersionDAO.create(version_create, session=db_session)


class TestToolVersionDAOGetById:
    """Test get_by_id operations for ToolVersionDAO."""
    
    async def test_get_by_id_returns_version(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test retrieving a tool version by ID."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
            implementation_ref="tools.test:func",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        fetched_version = await ToolVersionDAO.get_by_id(created_version.id, session=db_session)
        
        assert fetched_version is not None
        assert fetched_version.id == created_version.id
        assert fetched_version.version == "1.0.0"
        assert fetched_version.implementation_ref == "tools.test:func"
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        from uuid import uuid4
        
        nonexistent_id = uuid4()
        
        result = await ToolVersionDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that get_by_id returns a ToolVersion DTO."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        fetched_version = await ToolVersionDAO.get_by_id(created_version.id, session=db_session)
        
        assert isinstance(fetched_version, ToolVersion)


class TestToolVersionDAOGetByToolId:
    """Test get_by_tool_id operations for ToolVersionDAO."""
    
    async def test_get_by_tool_id_returns_versions(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test retrieving all versions for a tool."""
        # Create multiple versions
        for i in range(3):
            version_create = ToolVersionCreate(
                tool_id=sample_tool.id,
                version=f"1.{i}.0",
                is_default=(i == 2),
            )
            await ToolVersionDAO.create(version_create, session=db_session)
        
        versions = await ToolVersionDAO.get_by_tool_id(sample_tool.id, session=db_session)
        
        assert len(versions) == 3
        version_numbers = {v.version for v in versions}
        assert version_numbers == {"1.0.0", "1.1.0", "1.2.0"}
    
    async def test_get_by_tool_id_empty_returns_empty_list(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that get_by_tool_id returns empty list when no versions exist."""
        versions = await ToolVersionDAO.get_by_tool_id(sample_tool.id, session=db_session)
        
        assert versions == []
    
    async def test_get_by_tool_id_nonexistent_tool_returns_empty(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_by_tool_id returns empty list for nonexistent tool."""
        from uuid import uuid4
        
        versions = await ToolVersionDAO.get_by_tool_id(uuid4(), session=db_session)
        
        assert versions == []


class TestToolVersionDAOGetDefaultVersion:
    """Test get_default_version operations for ToolVersionDAO."""
    
    async def test_get_default_version_returns_version(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test retrieving the default version for a tool."""
        # Create versions with one default
        v1 = ToolVersionCreate(tool_id=sample_tool.id, version="1.0.0", is_default=False)
        v2 = ToolVersionCreate(tool_id=sample_tool.id, version="2.0.0", is_default=True)
        v3 = ToolVersionCreate(tool_id=sample_tool.id, version="3.0.0", is_default=False)
        
        await ToolVersionDAO.create(v1, session=db_session)
        await ToolVersionDAO.create(v2, session=db_session)
        await ToolVersionDAO.create(v3, session=db_session)
        
        default_version = await ToolVersionDAO.get_default_version(sample_tool.id, session=db_session)
        
        assert default_version is not None
        assert default_version.version == "2.0.0"
        assert default_version.is_default is True
    
    async def test_get_default_version_no_default_returns_none(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that get_default_version returns None when no default exists."""
        # Create versions without any default
        v1 = ToolVersionCreate(tool_id=sample_tool.id, version="1.0.0", is_default=False)
        v2 = ToolVersionCreate(tool_id=sample_tool.id, version="2.0.0", is_default=False)
        
        await ToolVersionDAO.create(v1, session=db_session)
        await ToolVersionDAO.create(v2, session=db_session)
        
        default_version = await ToolVersionDAO.get_default_version(sample_tool.id, session=db_session)
        
        assert default_version is None
    
    async def test_get_default_version_no_versions_returns_none(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that get_default_version returns None when no versions exist."""
        default_version = await ToolVersionDAO.get_default_version(sample_tool.id, session=db_session)
        
        assert default_version is None


class TestToolVersionDAOGetAll:
    """Test get_all operations for ToolVersionDAO."""
    
    async def test_get_all_returns_all_versions(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test retrieving all tool versions."""
        for i in range(3):
            version_create = ToolVersionCreate(
                tool_id=sample_tool.id,
                version=f"{i}.0.0",
            )
            await ToolVersionDAO.create(version_create, session=db_session)
        
        versions = await ToolVersionDAO.get_all(session=db_session)
        
        assert len(versions) == 3
        version_numbers = {v.version for v in versions}
        assert version_numbers == {"0.0.0", "1.0.0", "2.0.0"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that get_all returns empty list when no versions exist."""
        versions = await ToolVersionDAO.get_all(session=db_session)
        
        assert versions == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            version_create = ToolVersionCreate(
                tool_id=sample_tool.id,
                version=f"{i}.0.0",
            )
            await ToolVersionDAO.create(version_create, session=db_session)
        
        # Test limit
        versions_limited = await ToolVersionDAO.get_all(limit=2, session=db_session)
        assert len(versions_limited) == 2
        
        # Test offset
        versions_offset = await ToolVersionDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(versions_offset) == 2
        
        # Verify different versions returned
        ids_limited = {v.id for v in versions_limited}
        ids_offset = {v.id for v in versions_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that get_all returns ToolVersion DTOs."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        await ToolVersionDAO.create(version_create, session=db_session)
        
        versions = await ToolVersionDAO.get_all(session=db_session)
        
        assert len(versions) == 1
        assert isinstance(versions[0], ToolVersion)


class TestToolVersionDAOUpdate:
    """Test update operations for ToolVersionDAO."""
    
    async def test_update_version_implementation_ref(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test updating a version's implementation_ref."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
            implementation_ref="tools.old:func",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        version_update = ToolVersionUpdate(
            id=created_version.id,
            implementation_ref="tools.new:func",
        )
        updated_version = await ToolVersionDAO.update(version_update, session=db_session)
        
        assert updated_version is not None
        assert updated_version.implementation_ref == "tools.new:func"
    
    async def test_update_version_is_default(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test updating a version's is_default flag."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
            is_default=False,
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        version_update = ToolVersionUpdate(
            id=created_version.id,
            is_default=True,
        )
        updated_version = await ToolVersionDAO.update(version_update, session=db_session)
        
        assert updated_version is not None
        assert updated_version.is_default is True
    
    async def test_update_version_schemas(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test updating version schemas."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        new_input_schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        new_output_schema = {"type": "object", "properties": {"result": {"type": "string"}}}
        
        version_update = ToolVersionUpdate(
            id=created_version.id,
            input_schema=new_input_schema,
            output_schema=new_output_schema,
        )
        updated_version = await ToolVersionDAO.update(version_update, session=db_session)
        
        assert updated_version is not None
        assert updated_version.input_schema == new_input_schema
        assert updated_version.output_schema == new_output_schema
    
    async def test_update_nonexistent_version_returns_none(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that updating a nonexistent version returns None."""
        from uuid import uuid4
        
        version_update = ToolVersionUpdate(
            id=uuid4(),
            implementation_ref="nonexistent",
        )
        
        result = await ToolVersionDAO.update(version_update, session=db_session)
        
        assert result is None
    
    async def test_update_returns_dto(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that update returns a ToolVersion DTO."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        version_update = ToolVersionUpdate(
            id=created_version.id,
            implementation_ref="updated:ref",
        )
        updated_version = await ToolVersionDAO.update(version_update, session=db_session)
        
        assert isinstance(updated_version, ToolVersion)


class TestToolVersionDAODelete:
    """Test delete operations for ToolVersionDAO."""
    
    async def test_delete_existing_version(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test deleting an existing tool version."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        result = await ToolVersionDAO.delete(created_version.id, session=db_session)
        
        assert result is True
        
        # Verify version is deleted
        fetched = await ToolVersionDAO.get_by_id(created_version.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_version_returns_false(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that deleting a nonexistent version returns False."""
        from uuid import uuid4
        
        result = await ToolVersionDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestToolVersionDAOExists:
    """Test exists operations for ToolVersionDAO."""
    
    async def test_exists_returns_true_for_existing_version(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that exists returns True for existing version."""
        version_create = ToolVersionCreate(
            tool_id=sample_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        
        result = await ToolVersionDAO.exists(created_version.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_version(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that exists returns False for nonexistent version."""
        from uuid import uuid4
        
        result = await ToolVersionDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestToolVersionDAOCount:
    """Test count operations for ToolVersionDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that count returns the correct number of versions."""
        for i in range(3):
            version_create = ToolVersionCreate(
                tool_id=sample_tool.id,
                version=f"{i}.0.0",
            )
            await ToolVersionDAO.create(version_create, session=db_session)
        
        count = await ToolVersionDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that count returns 0 for empty table."""
        count = await ToolVersionDAO.count(session=db_session)
        
        assert count == 0


class TestToolVersionDAOCountByTool:
    """Test count_by_tool operations for ToolVersionDAO."""
    
    async def test_count_by_tool_returns_correct_number(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that count_by_tool returns correct count for a tool."""
        for i in range(3):
            version_create = ToolVersionCreate(
                tool_id=sample_tool.id,
                version=f"{i}.0.0",
            )
            await ToolVersionDAO.create(version_create, session=db_session)
        
        count = await ToolVersionDAO.count_by_tool(sample_tool.id, session=db_session)
        
        assert count == 3
    
    async def test_count_by_tool_no_versions_returns_zero(
        self, db_session: AsyncSession, sample_tool: Tool
    ):
        """Test that count_by_tool returns 0 for tool with no versions."""
        count = await ToolVersionDAO.count_by_tool(sample_tool.id, session=db_session)
        
        assert count == 0


class TestToolVersionDAOCascadeDelete:
    """Test cascade delete behavior."""
    
    async def test_version_deleted_when_tool_deleted(
        self, db_session: AsyncSession, clean_tables: None
    ):
        """Test that versions are deleted when parent tool is deleted."""
        # Create tool
        tool_create = ToolCreate(name="cascade_test_tool")
        created_tool = await ToolDAO.create(tool_create, session=db_session)
        
        # Create version
        version_create = ToolVersionCreate(
            tool_id=created_tool.id,
            version="1.0.0",
        )
        created_version = await ToolVersionDAO.create(version_create, session=db_session)
        version_id = created_version.id
        
        # Delete tool
        await ToolDAO.delete(created_tool.id, session=db_session)
        
        # Verify version is also deleted
        from sqlalchemy import select
        result = await db_session.execute(
            select(ToolVersionEntity).where(ToolVersionEntity.id == version_id)
        )
        assert result.scalar_one_or_none() is None