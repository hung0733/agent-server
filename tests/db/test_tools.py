# pyright: reportMissingImports=false
"""
Tests for tool database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and JSONB validation for tools and tool_versions tables.
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
from db.entity.tool_entity import Tool, ToolVersion


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation.
    """
    import os
    
    # Use the main database for testing (read from environment)
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
        # Create tools table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tools (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create tool_versions table with FK constraint
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tool_versions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                version VARCHAR(50) NOT NULL,
                input_schema JSONB,
                output_schema JSONB,
                implementation_ref TEXT,
                config_json JSONB,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tools_is_active ON tools(is_active)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tool_versions_tool_id 
            ON tool_versions(tool_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tool_versions_version 
            ON tool_versions(version)
        """))
        # Partial unique index for default version
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_versions_default
            ON tool_versions(tool_id)
            WHERE is_default = true
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_tool_versions_default"))
        await conn.execute(text("DROP TABLE IF EXISTS tool_versions"))
        await conn.execute(text("DROP TABLE IF EXISTS tools"))
    
    await engine.dispose()


class TestToolSchema:
    """Test tools schema creation and structure."""
    
    async def test_tools_table_exists(self, db_session: AsyncSession):
        """Test that the tools table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'tools'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "tools"
    
    async def test_tools_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in tools table."""
        expected_columns = {
            'id', 'name', 'description', 'is_active', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'tools'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_tools_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'tools'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_tools_name' in indexes
        assert 'idx_tools_is_active' in indexes
    
    async def test_unique_constraint_on_name(self, db_session: AsyncSession):
        """Test that name has a unique constraint."""
        # Insert first tool
        await db_session.execute(text("""
            INSERT INTO tools (name, description) 
            VALUES ('TestTool', 'First test tool')
        """))
        await db_session.commit()
        
        # Try to insert duplicate name - should fail
        with pytest.raises(IntegrityError):
            await db_session.execute(text("""
                INSERT INTO tools (name, description) 
                VALUES ('TestTool', 'Duplicate test tool')
            """))
            await db_session.commit()


class TestToolVersionSchema:
    """Test tool_versions schema creation and structure."""
    
    async def test_tool_versions_table_exists(self, db_session: AsyncSession):
        """Test that the tool_versions table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'tool_versions'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "tool_versions"
    
    async def test_tool_versions_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in tool_versions table."""
        expected_columns = {
            'id', 'tool_id', 'version', 'input_schema', 'output_schema',
            'implementation_ref', 'config_json', 'is_default', 'created_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'tool_versions'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_tool_versions_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'tool_versions'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_tool_versions_tool_id' in indexes
        assert 'idx_tool_versions_version' in indexes
        assert 'idx_tool_versions_default' in indexes
    
    async def test_partial_unique_index_on_default(self, db_session: AsyncSession):
        """Test that only one default version per tool is allowed."""
        # Insert a tool first
        await db_session.execute(text("""
            INSERT INTO tools (id, name) 
            VALUES (gen_random_uuid(), 'TestTool')
        """))
        await db_session.commit()
        
        # Get tool ID
        result = await db_session.execute(
            text("SELECT id FROM tools WHERE name = 'TestTool'")
        )
        tool_id = result.scalar_one()
        
        # Insert first default version - should succeed
        await db_session.execute(text(f"""
            INSERT INTO tool_versions (tool_id, version, is_default) 
            VALUES ('{tool_id}', '1.0.0', true)
        """))
        await db_session.commit()
        
        # Try to insert second default version - should fail
        with pytest.raises(IntegrityError):
            await db_session.execute(text(f"""
                INSERT INTO tool_versions (tool_id, version, is_default) 
                VALUES ('{tool_id}', '2.0.0', true)
            """))
            await db_session.commit()
    
    async def test_multiple_non_default_versions_allowed(self, db_session: AsyncSession):
        """Test that multiple non-default versions are allowed."""
        # Insert a tool first
        await db_session.execute(text("""
            INSERT INTO tools (id, name) 
            VALUES (gen_random_uuid(), 'MultiVersionTool')
        """))
        await db_session.commit()
        
        # Get tool ID
        result = await db_session.execute(
            text("SELECT id FROM tools WHERE name = 'MultiVersionTool'")
        )
        tool_id = result.scalar_one()
        
        # Insert multiple non-default versions
        await db_session.execute(text(f"""
            INSERT INTO tool_versions (tool_id, version, is_default) 
            VALUES ('{tool_id}', '1.0.0', false)
        """))
        await db_session.execute(text(f"""
            INSERT INTO tool_versions (tool_id, version, is_default) 
            VALUES ('{tool_id}', '1.1.0', false)
        """))
        await db_session.execute(text(f"""
            INSERT INTO tool_versions (tool_id, version, is_default) 
            VALUES ('{tool_id}', '2.0.0', false)
        """))
        await db_session.commit()
        
        # Verify all three exist
        result = await db_session.execute(
            text(f"SELECT COUNT(*) FROM tool_versions WHERE tool_id = '{tool_id}'")
        )
        count = result.scalar_one()
        assert count == 3


class TestToolCRUD:
    """Test CRUD operations for Tool model."""
    
    async def test_create_tool_minimal(self, db_session: AsyncSession):
        """Test creating a tool with minimal fields."""
        tool = Tool(name="MinimalTool")
        db_session.add(tool)
        await db_session.commit()
        await db_session.refresh(tool)
        
        assert tool.id is not None
        assert isinstance(tool.id, UUID)
        assert tool.name == "MinimalTool"
        assert tool.description is None
        assert tool.is_active is True
        assert tool.created_at is not None
        assert tool.updated_at is not None
    
    async def test_create_tool_full(self, db_session: AsyncSession):
        """Test creating a tool with all fields."""
        tool = Tool(
            name="WebSearchTool",
            description="A tool for searching the web",
            is_active=True,
        )
        db_session.add(tool)
        await db_session.commit()
        await db_session.refresh(tool)
        
        assert tool.name == "WebSearchTool"
        assert tool.description == "A tool for searching the web"
        assert tool.is_active is True
    
    async def test_update_tool(self, db_session: AsyncSession):
        """Test updating a tool."""
        tool = Tool(name="UpdateTest")
        db_session.add(tool)
        await db_session.commit()
        
        original_updated_at = tool.updated_at
        await asyncio.sleep(0.01)  # Ensure time difference
        
        tool.description = "Updated description"
        tool.is_active = False
        await db_session.commit()
        await db_session.refresh(tool)
        
        assert tool.description == "Updated description"
        assert tool.is_active is False
        assert tool.updated_at > original_updated_at
    
    async def test_delete_tool(self, db_session: AsyncSession):
        """Test deleting a tool."""
        tool = Tool(name="DeleteTest")
        db_session.add(tool)
        await db_session.commit()
        
        await db_session.delete(tool)
        await db_session.commit()
        
        result = await db_session.execute(
            select(Tool).where(Tool.id == tool.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_get_tool_by_id(self, db_session: AsyncSession):
        """Test retrieving a tool by ID."""
        tool = Tool(name="GetTest", description="Test for retrieval")
        db_session.add(tool)
        await db_session.commit()
        
        result = await db_session.execute(
            select(Tool).where(Tool.id == tool.id)
        )
        retrieved = result.scalar_one()
        
        assert retrieved.name == "GetTest"
        assert retrieved.description == "Test for retrieval"
    
    async def test_list_tools_filter_by_is_active(self, db_session: AsyncSession):
        """Test filtering tools by is_active flag."""
        # Create active tool
        active_tool = Tool(name="ActiveTool", is_active=True)
        db_session.add(active_tool)
        
        # Create inactive tool
        inactive_tool = Tool(name="InactiveTool", is_active=False)
        db_session.add(inactive_tool)
        
        await db_session.commit()
        
        # Query active tools
        result = await db_session.execute(
            select(Tool).where(Tool.is_active == True)
        )
        active_tools = result.scalars().all()
        assert len(active_tools) == 1
        assert active_tools[0].name == "ActiveTool"
        
        # Query inactive tools
        result = await db_session.execute(
            select(Tool).where(Tool.is_active == False)
        )
        inactive_tools = result.scalars().all()
        assert len(inactive_tools) == 1
        assert inactive_tools[0].name == "InactiveTool"


class TestToolVersionCRUD:
    """Test CRUD operations for ToolVersion model."""
    
    async def test_create_tool_version_minimal(self, db_session: AsyncSession):
        """Test creating a tool version with minimal fields."""
        # Create tool first
        tool = Tool(name="VersionTestTool")
        db_session.add(tool)
        await db_session.commit()
        
        version = ToolVersion(
            tool_id=tool.id,
            version="1.0.0",
        )
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)
        
        assert version.id is not None
        assert isinstance(version.id, UUID)
        assert version.tool_id == tool.id
        assert version.version == "1.0.0"
        assert version.input_schema is None
        assert version.output_schema is None
        assert version.implementation_ref is None
        assert version.config_json is None
        assert version.is_default is False
        assert version.created_at is not None
    
    async def test_create_tool_version_full(self, db_session: AsyncSession):
        """Test creating a tool version with all fields."""
        # Create tool first
        tool = Tool(name="FullVersionTool")
        db_session.add(tool)
        await db_session.commit()
        
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        }
        output_schema = {
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": {"type": "object"}}
            },
        }
        config_json = {
            "timeout": 30,
            "max_results": 10,
        }
        
        version = ToolVersion(
            tool_id=tool.id,
            version="1.0.0",
            input_schema=input_schema,
            output_schema=output_schema,
            implementation_ref="tools.web_search:search",
            config_json=config_json,
            is_default=True,
        )
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)
        
        assert version.version == "1.0.0"
        assert isinstance(version.input_schema, dict)
        assert version.input_schema["properties"]["query"]["type"] == "string"
        assert isinstance(version.output_schema, dict)
        assert version.implementation_ref == "tools.web_search:search"
        assert isinstance(version.config_json, dict)
        assert version.config_json["timeout"] == 30
        assert version.is_default is True
    
    async def test_update_tool_version(self, db_session: AsyncSession):
        """Test updating a tool version."""
        # Create tool and version
        tool = Tool(name="UpdateVersionTool")
        db_session.add(tool)
        await db_session.commit()
        
        version = ToolVersion(tool_id=tool.id, version="1.0.0", is_default=False)
        db_session.add(version)
        await db_session.commit()
        
        # Update version
        version.implementation_ref = "tools.web_search:search_v2"
        version.is_default = True
        await db_session.commit()
        await db_session.refresh(version)
        
        assert version.implementation_ref == "tools.web_search:search_v2"
        assert version.is_default is True
    
    async def test_delete_tool_version(self, db_session: AsyncSession):
        """Test deleting a tool version."""
        # Create tool and version
        tool = Tool(name="DeleteVersionTool")
        db_session.add(tool)
        await db_session.commit()
        
        version = ToolVersion(tool_id=tool.id, version="1.0.0")
        db_session.add(version)
        await db_session.commit()
        
        await db_session.delete(version)
        await db_session.commit()
        
        result = await db_session.execute(
            select(ToolVersion).where(ToolVersion.id == version.id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_get_tool_version_by_id(self, db_session: AsyncSession):
        """Test retrieving a tool version by ID."""
        # Create tool and version
        tool = Tool(name="GetVersionTool")
        db_session.add(tool)
        await db_session.commit()
        
        version = ToolVersion(
            tool_id=tool.id,
            version="2.0.0",
            is_default=False,
        )
        db_session.add(version)
        await db_session.commit()
        
        result = await db_session.execute(
            select(ToolVersion).where(ToolVersion.id == version.id)
        )
        retrieved = result.scalar_one()
        
        assert retrieved.version == "2.0.0"
        assert retrieved.tool_id == tool.id
    
    async def test_list_versions_by_tool_id(self, db_session: AsyncSession):
        """Test retrieving all versions for a tool."""
        # Create tool
        tool = Tool(name="MultiVersionTool")
        db_session.add(tool)
        await db_session.commit()
        
        # Create multiple versions
        v1 = ToolVersion(tool_id=tool.id, version="1.0.0", is_default=False)
        v2 = ToolVersion(tool_id=tool.id, version="1.1.0", is_default=False)
        v3 = ToolVersion(tool_id=tool.id, version="2.0.0", is_default=True)
        db_session.add_all([v1, v2, v3])
        await db_session.commit()
        
        # Query versions for this tool
        result = await db_session.execute(
            select(ToolVersion).where(ToolVersion.tool_id == tool.id)
        )
        versions = result.scalars().all()
        
        assert len(versions) == 3
        version_numbers = {v.version for v in versions}
        assert version_numbers == {"1.0.0", "1.1.0", "2.0.0"}
    
    async def test_get_default_version_for_tool(self, db_session: AsyncSession):
        """Test retrieving the default version for a tool."""
        # Create tool
        tool = Tool(name="DefaultVersionTool")
        db_session.add(tool)
        await db_session.commit()
        
        # Create versions with one default
        v1 = ToolVersion(tool_id=tool.id, version="1.0.0", is_default=False)
        v2 = ToolVersion(tool_id=tool.id, version="2.0.0", is_default=True)
        v3 = ToolVersion(tool_id=tool.id, version="3.0.0", is_default=False)
        db_session.add_all([v1, v2, v3])
        await db_session.commit()
        
        # Query default version
        result = await db_session.execute(
            select(ToolVersion).where(
                ToolVersion.tool_id == tool.id,
                ToolVersion.is_default == True
            )
        )
        default_version = result.scalar_one()
        
        assert default_version.version == "2.0.0"


class TestToolVersionForeignKeyConstraints:
    """Test foreign key constraints for tool_versions."""
    
    async def test_cascade_delete_on_tool_delete(self, db_session: AsyncSession):
        """Test that deleting a tool cascades to delete its versions."""
        # Create tool with version
        tool = Tool(name="CascadeDeleteTool")
        db_session.add(tool)
        await db_session.commit()
        
        version = ToolVersion(tool_id=tool.id, version="1.0.0")
        db_session.add(version)
        await db_session.commit()
        
        version_id = version.id
        tool_id = tool.id
        
        # Delete tool
        await db_session.delete(tool)
        await db_session.commit()
        
        # Verify tool is deleted
        result = await db_session.execute(
            select(Tool).where(Tool.id == tool_id)
        )
        assert result.scalar_one_or_none() is None
        
        # Verify version is also deleted (CASCADE)
        result = await db_session.execute(
            select(ToolVersion).where(ToolVersion.id == version_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_cannot_create_version_without_tool(self, db_session: AsyncSession):
        """Test that creating a version with invalid tool_id fails."""
        fake_tool_id = uuid4()
        
        version = ToolVersion(tool_id=fake_tool_id, version="1.0.0")
        db_session.add(version)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestToolPydanticModels:
    """Test Pydantic model validation."""
    
    def test_tool_create_validation(self):
        """Test ToolCreate model validation."""
        from db.models.tool import ToolCreate
        
        # Valid creation
        tool_data = {
            "name": "ValidTool",
            "description": "A valid tool",
            "is_active": True,
        }
        tool = ToolCreate(**tool_data)
        assert tool.name == "ValidTool"
        assert tool.description == "A valid tool"
        assert tool.is_active is True
    
    def test_tool_version_create_validation(self):
        """Test ToolVersionCreate model validation."""
        from db.models.tool import ToolVersionCreate
        
        tool_id = uuid4()
        version_data = {
            "tool_id": tool_id,
            "version": "1.0.0",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "implementation_ref": "tools.test:test_func",
            "config_json": {"key": "value"},
            "is_default": True,
        }
        version = ToolVersionCreate(**version_data)
        assert version.tool_id == tool_id
        assert version.version == "1.0.0"
        assert version.is_default is True
    
    def test_tool_model_from_attributes(self):
        """Test Tool model with from_attributes."""
        from db.models.tool import Tool
        
        # Simulate ORM mode
        tool = Tool.model_validate(
            {
                "id": str(uuid4()),
                "name": "ORMTool",
                "description": "Test tool",
                "is_active": True,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
            from_attributes=True,
        )
        assert tool.name == "ORMTool"
        assert tool.description == "Test tool"
