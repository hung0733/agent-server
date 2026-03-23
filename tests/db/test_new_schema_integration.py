"""
Comprehensive integration tests for new database schema changes.

Tests new fields and tables: users.phone_no, agent_instances fields,
MCP clients/tools, memory_blocks, and checkpoint tables.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

from db import create_engine, AsyncSession
from db.entity.user_entity import User
from db.entity.agent_entity import AgentType, AgentInstance


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with access to all tables.
    
    This fixture connects to the main database where migrations have been applied.
    """
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432')
    db_user = os.getenv('POSTGRES_USER', 'agentserver')
    db_password = os.getenv('POSTGRES_PASSWORD', 'testpass')
    db_name = os.getenv('POSTGRES_DB', 'agentserver')
    
    dsn = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    engine = create_engine(dsn=dsn)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        yield session


class TestUsersPhoneNumber:
    """Test phone_no field in users table."""
    
    async def test_create_user_with_phone_no(self, db_session: AsyncSession):
        """Test creating user with phone_no field."""
        # Use raw SQL since User model doesn't have phone_no yet
        result = await db_session.execute(text("""
            INSERT INTO users (username, email, phone_no)
            VALUES (:username, :email, :phone_no)
            RETURNING id, username, email, phone_no
        """), {
            "username": f"test_user_{uuid4().hex[:8]}",
            "email": f"test_{uuid4().hex[:8]}@example.com",
            "phone_no": "+852-9123-4567"
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.phone_no == "+852-9123-4567"
    
    async def test_create_user_without_phone_no(self, db_session: AsyncSession):
        """Test creating user without phone_no (nullable field)."""
        result = await db_session.execute(text("""
            INSERT INTO users (username, email, phone_no)
            VALUES (:username, :email, :phone_no)
            RETURNING id, phone_no
        """), {
            "username": f"test_user2_{uuid4().hex[:8]}",
            "email": f"test2_{uuid4().hex[:8]}@example.com",
            "phone_no": None
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.phone_no is None
    
    async def test_update_user_phone_no(self, db_session: AsyncSession):
        """Test updating user's phone_no field."""
        # Create user first
        result = await db_session.execute(text("""
            INSERT INTO users (username, email, phone_no)
            VALUES (:username, :email, :phone_no)
            RETURNING id
        """), {
            "username": f"test_user3_{uuid4().hex[:8]}",
            "email": f"test3_{uuid4().hex[:8]}@example.com",
            "phone_no": None
        })
        user_id = result.scalar()
        await db_session.commit()
        
        # Update phone_no
        result = await db_session.execute(text("""
            UPDATE users SET phone_no = :phone_no
            WHERE id = :user_id
            RETURNING phone_no
        """), {
            "user_id": user_id,
            "phone_no": "12345678"
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.phone_no == "12345678"
    
    async def test_users_table_existing_functionality(self, db_session: AsyncSession):
        """Test that existing users table functionality still works."""
        user = User(
            username=f"existing_func_{uuid4().hex[:8]}",
            email=f"existing_{uuid4().hex[:8]}@example.com",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        assert user.id is not None
        assert user.username.startswith("existing_func_")
        assert user.is_active is True


class TestAgentInstancesNewFields:
    """Test new fields in agent_instances table."""
    
    @pytest_asyncio.fixture
    async def setup_agent_test_data(self, db_session: AsyncSession):
        """Setup test data for agent instances tests."""
        # Create user
        user_result = await db_session.execute(text("""
            INSERT INTO users (username, email)
            VALUES (:username, :email)
            RETURNING id
        """), {
            "username": f"agent_test_user_{uuid4().hex[:8]}",
            "email": f"agent_test_{uuid4().hex[:8]}@example.com"
        })
        user_id = user_result.scalar()
        
        # Create agent type
        agent_type_result = await db_session.execute(text("""
            INSERT INTO agent_types (name, description)
            VALUES (:name, :description)
            RETURNING id
        """), {
            "name": f"TestAgentType_{uuid4().hex[:8]}",
            "description": "Test agent type"
        })
        agent_type_id = agent_type_result.scalar()
        
        # Create endpoint group
        endpoint_group_result = await db_session.execute(text("""
            INSERT INTO llm_endpoint_groups (user_id, name, description)
            VALUES (:user_id, :name, :description)
            RETURNING id
        """), {
            "user_id": user_id,
            "name": f"TestEndpointGroup_{uuid4().hex[:8]}",
            "description": "Test endpoint group"
        })
        endpoint_group_id = endpoint_group_result.scalar()
        
        await db_session.commit()
        
        return {
            "user_id": user_id,
            "agent_type_id": agent_type_id,
            "endpoint_group_id": endpoint_group_id
        }
    
    async def test_create_agent_with_all_new_fields(self, db_session: AsyncSession, setup_agent_test_data):
        """Test creating agent instance with all 4 new fields."""
        data = setup_agent_test_data
        
        result = await db_session.execute(text("""
            INSERT INTO agent_instances (
                agent_type_id, user_id, endpoint_group_id,
                agent_id, phone_no, whatsapp_key, status
            ) VALUES (
                :agent_type_id, :user_id, :endpoint_group_id,
                :agent_id, :phone_no, :whatsapp_key, :status
            )
            RETURNING id, agent_id, endpoint_group_id, phone_no, whatsapp_key
        """), {
            "agent_type_id": data["agent_type_id"],
            "user_id": data["user_id"],
            "endpoint_group_id": data["endpoint_group_id"],
            "agent_id": f"agent_{uuid4().hex[:8]}",
            "phone_no": "+852-9876-5432",
            "whatsapp_key": "whatsapp_secret_key_123",
            "status": "idle"
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.agent_id is not None
        assert row.endpoint_group_id == data["endpoint_group_id"]
        assert row.phone_no == "+852-9876-5432"
        assert row.whatsapp_key == "whatsapp_secret_key_123"
    
    async def test_agent_instances_existing_functionality(self, db_session: AsyncSession, setup_agent_test_data):
        """Test that existing agent_instances functionality still works."""
        data = setup_agent_test_data
        
        agent = AgentInstance(
            agent_type_id=data["agent_type_id"],
            user_id=data["user_id"],
            name="TestAgent-Existing",
            status="idle",
            config={"test": True}
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.id is not None
        assert agent.name == "TestAgent-Existing"
        assert agent.config == {"test": True}


class TestMCPClientsAndTools:
    """Test MCP clients and tools tables."""
    
    @pytest_asyncio.fixture
    async def setup_mcp_test_data(self, db_session: AsyncSession):
        """Setup test data for MCP tests."""
        # Create user
        user_result = await db_session.execute(text("""
            INSERT INTO users (username, email)
            VALUES (:username, :email)
            RETURNING id
        """), {
            "username": f"mcp_test_user_{uuid4().hex[:8]}",
            "email": f"mcp_test_{uuid4().hex[:8]}@example.com"
        })
        user_id = user_result.scalar()
        
        # Create tool
        tool_result = await db_session.execute(text("""
            INSERT INTO tools (name, description)
            VALUES (:name, :description)
            RETURNING id
        """), {
            "name": f"mcp_test_tool_{uuid4().hex[:8]}",
            "description": "Test tool for MCP"
        })
        tool_id = tool_result.scalar()
        
        await db_session.commit()
        
        return {"user_id": user_id, "tool_id": tool_id}
    
    async def test_create_mcp_client(self, db_session: AsyncSession, setup_mcp_test_data):
        """Test creating MCP client."""
        data = setup_mcp_test_data
        
        result = await db_session.execute(text("""
            INSERT INTO mcp_clients (
                user_id, name, protocol, base_url, auth_type, status
            ) VALUES (
                :user_id, :name, :protocol, :base_url, :auth_type, :status
            )
            RETURNING id, user_id, name, protocol, status
        """), {
            "user_id": data["user_id"],
            "name": "Test MCP Client",
            "protocol": "http",
            "base_url": "https://mcp.example.com",
            "auth_type": "api_key",
            "status": "connected"
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.name == "Test MCP Client"
        assert row.protocol == "http"
        assert row.status == "connected"
    
    async def test_create_mcp_tool(self, db_session: AsyncSession, setup_mcp_test_data):
        """Test creating MCP tool mapping."""
        data = setup_mcp_test_data
        
        # First create MCP client
        client_result = await db_session.execute(text("""
            INSERT INTO mcp_clients (user_id, name, protocol, base_url, status)
            VALUES (:user_id, :name, 'http', :base_url, 'connected')
            RETURNING id
        """), {
            "user_id": data["user_id"],
            "name": "MCP Client for Tool Test",
            "base_url": "https://mcp.example.com"
        })
        client_id = client_result.scalar()
        
        # Now create MCP tool
        result = await db_session.execute(text("""
            INSERT INTO mcp_tools (
                mcp_client_id, tool_id, mcp_tool_name, mcp_tool_description
            ) VALUES (
                :client_id, :tool_id, :mcp_tool_name, :mcp_tool_description
            )
            RETURNING id, mcp_client_id, tool_id, mcp_tool_name
        """), {
            "client_id": client_id,
            "tool_id": data["tool_id"],
            "mcp_tool_name": "test_tool",
            "mcp_tool_description": "A test MCP tool"
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.mcp_client_id == client_id
        assert row.tool_id == data["tool_id"]
        assert row.mcp_tool_name == "test_tool"
    
    async def test_mcp_client_cascade_delete(self, db_session: AsyncSession, setup_mcp_test_data):
        """Test that deleting MCP client cascades to mcp_tools."""
        data = setup_mcp_test_data
        
        # Create client and tool
        client_result = await db_session.execute(text("""
            INSERT INTO mcp_clients (user_id, name, protocol, base_url, status)
            VALUES (:user_id, :name, 'http', 'https://mcp.example.com', 'connected')
            RETURNING id
        """), {
            "user_id": data["user_id"],
            "name": "Cascade Test Client"
        })
        client_id = client_result.scalar()
        
        mcp_tool_result = await db_session.execute(text("""
            INSERT INTO mcp_tools (mcp_client_id, tool_id, mcp_tool_name)
            VALUES (:client_id, :tool_id, 'test_tool')
            RETURNING id
        """), {
            "client_id": client_id,
            "tool_id": data["tool_id"]
        })
        mcp_tool_id = mcp_tool_result.scalar()
        await db_session.commit()
        
        # Delete client
        await db_session.execute(text("""
            DELETE FROM mcp_clients WHERE id = :client_id
        """), {"client_id": client_id})
        await db_session.commit()
        
        # Verify MCP tool is also deleted
        result = await db_session.execute(text("""
            SELECT id FROM mcp_tools WHERE id = :mcp_tool_id
        """), {"mcp_tool_id": mcp_tool_id})
        row = result.fetchone()
        
        assert row is None  # Should be cascade deleted


class TestMemoryBlocks:
    """Test memory_blocks table with three memory types."""
    
    @pytest_asyncio.fixture
    async def setup_memory_test_data(self, db_session: AsyncSession):
        """Setup test data for memory tests."""
        # Create user
        user_result = await db_session.execute(text("""
            INSERT INTO users (username, email)
            VALUES (:username, :email)
            RETURNING id
        """), {
            "username": f"mem_test_user_{uuid4().hex[:8]}",
            "email": f"mem_test_{uuid4().hex[:8]}@example.com"
        })
        user_id = user_result.scalar()
        
        # Create agent type and instance
        agent_type_result = await db_session.execute(text("""
            INSERT INTO agent_types (name)
            VALUES (:name)
            RETURNING id
        """), {
            "name": f"MemTestAgentType_{uuid4().hex[:8]}"
        })
        agent_type_id = agent_type_result.scalar()
        
        agent_result = await db_session.execute(text("""
            INSERT INTO agent_instances (agent_type_id, user_id, status)
            VALUES (:agent_type_id, :user_id, 'idle')
            RETURNING id
        """), {
            "agent_type_id": agent_type_id,
            "user_id": user_id
        })
        agent_instance_id = agent_result.scalar()
        
        await db_session.commit()
        
        return {"agent_instance_id": agent_instance_id}
    
    async def test_create_memory_blocks_all_types(self, db_session: AsyncSession, setup_memory_test_data):
        """Test creating memory blocks for all three memory types."""
        data = setup_memory_test_data
        
        memory_types = ["IDENTITY", "SOUL", "USER_PROFILE"]
        created_ids = []
        
        for memory_type in memory_types:
            result = await db_session.execute(text("""
                INSERT INTO memory_blocks (
                    agent_instance_id, memory_type, content, version
                ) VALUES (
                    :agent_instance_id, :memory_type, :content, :version
                )
                RETURNING id, memory_type
            """), {
                "agent_instance_id": data["agent_instance_id"],
                "memory_type": memory_type,
                "content": f"# {memory_type} Memory\nThis is test content",
                "version": 1
            })
            row = result.fetchone()
            created_ids.append(row.id)
        
        await db_session.commit()
        
        assert len(created_ids) == 3
        
        # Verify all three types exist
        result = await db_session.execute(text("""
            SELECT memory_type FROM memory_blocks
            WHERE agent_instance_id = :agent_instance_id
            ORDER BY memory_type
        """), {"agent_instance_id": data["agent_instance_id"]})
        rows = result.fetchall()
        
        assert len(rows) == 3
        assert [r.memory_type for r in rows] == ["IDENTITY", "SOUL", "USER_PROFILE"]
    
    async def test_memory_block_unique_constraint(self, db_session: AsyncSession, setup_memory_test_data):
        """Test unique constraint on (agent_instance_id, memory_type)."""
        data = setup_memory_test_data
        
        # Create first memory block
        await db_session.execute(text("""
            INSERT INTO memory_blocks (agent_instance_id, memory_type, content)
            VALUES (:agent_instance_id, 'IDENTITY', 'First memory')
        """), {"agent_instance_id": data["agent_instance_id"]})
        await db_session.commit()
        
        # Try to create duplicate - should fail
        with pytest.raises(Exception) as exc_info:
            await db_session.execute(text("""
                INSERT INTO memory_blocks (agent_instance_id, memory_type, content)
                VALUES (:agent_instance_id, 'IDENTITY', 'Duplicate memory')
            """), {"agent_instance_id": data["agent_instance_id"]})
            await db_session.commit()
        
        # Should raise unique constraint violation
        assert "unique" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()
    
    async def test_memory_block_cascade_delete(self, db_session: AsyncSession, setup_memory_test_data):
        """Test that deleting agent instance cascades to memory_blocks."""
        data = setup_memory_test_data
        
        # Create memory block
        mem_result = await db_session.execute(text("""
            INSERT INTO memory_blocks (agent_instance_id, memory_type, content)
            VALUES (:agent_instance_id, 'SOUL', 'Test soul memory')
            RETURNING id
        """), {"agent_instance_id": data["agent_instance_id"]})
        memory_id = mem_result.scalar()
        await db_session.commit()
        
        # Get agent instance ID to delete
        agent_result = await db_session.execute(text("""
            SELECT agent_instance_id FROM memory_blocks WHERE id = :memory_id
        """), {"memory_id": memory_id})
        agent_instance_id = agent_result.scalar()
        
        # Delete agent instance
        await db_session.execute(text("""
            DELETE FROM agent_instances WHERE id = :agent_instance_id
        """), {"agent_instance_id": agent_instance_id})
        await db_session.commit()
        
        # Verify memory is cascade deleted
        result = await db_session.execute(text("""
            SELECT id FROM memory_blocks WHERE id = :memory_id
        """), {"memory_id": memory_id})
        row = result.fetchone()
        
        assert row is None


class TestCheckpointTables:
    """Test checkpoint tables for LangGraph compatibility."""
    
    async def test_create_checkpoint(self, db_session: AsyncSession):
        """Test creating checkpoint with composite key."""
        import json
        thread_id = f"thread_{uuid4().hex[:8]}"
        checkpoint_id = f"checkpoint_{uuid4().hex[:8]}"
        
        result = await db_session.execute(text("""
            INSERT INTO checkpoints (
                thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint
            ) VALUES (
                :thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, CAST(:checkpoint AS JSONB)
            )
            RETURNING thread_id, checkpoint_ns, checkpoint_id
        """), {
            "thread_id": thread_id,
            "checkpoint_ns": "test_namespace",
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": None,
            "checkpoint": json.dumps({"state": "test_state", "step": 1})
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.thread_id == thread_id
        assert row.checkpoint_ns == "test_namespace"
        assert row.checkpoint_id == checkpoint_id
    
    async def test_create_checkpoint_blob(self, db_session: AsyncSession):
        """Test creating checkpoint blob with composite key."""
        thread_id = f"thread_{uuid4().hex[:8]}"
        
        result = await db_session.execute(text("""
            INSERT INTO checkpoint_blobs (
                thread_id, checkpoint_ns, channel, version, type, blob
            ) VALUES (
                :thread_id, :checkpoint_ns, :channel, :version, :type, :blob
            )
            RETURNING thread_id, channel, version
        """), {
            "thread_id": thread_id,
            "checkpoint_ns": "test_ns",
            "channel": "test_channel",
            "version": "v1",
            "type": "json",
            "blob": b'\x00\x01\x02\x03'
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.thread_id == thread_id
        assert row.channel == "test_channel"
        assert row.version == "v1"
    
    async def test_create_checkpoint_write(self, db_session: AsyncSession):
        """Test creating checkpoint write with composite key."""
        thread_id = f"thread_{uuid4().hex[:8]}"
        checkpoint_id = f"checkpoint_{uuid4().hex[:8]}"
        
        result = await db_session.execute(text("""
            INSERT INTO checkpoint_writes (
                thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob
            ) VALUES (
                :thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :blob
            )
            RETURNING thread_id, checkpoint_id, task_id, idx
        """), {
            "thread_id": thread_id,
            "checkpoint_ns": "test_ns",
            "checkpoint_id": checkpoint_id,
            "task_id": f"task_{uuid4().hex[:8]}",
            "idx": 0,
            "channel": "test_channel",
            "type": "json",
            "blob": b'\x00\x01\x02\x03'
        })
        row = result.fetchone()
        await db_session.commit()
        
        assert row is not None
        assert row.thread_id == thread_id
        assert row.checkpoint_id == checkpoint_id
        assert row.idx == 0


class TestTableRelationships:
    """Test join queries and relationships between tables."""
    
    @pytest_asyncio.fixture
    async def setup_relationship_test_data(self, db_session: AsyncSession):
        """Setup complex test data for relationship tests."""
        # Create user with phone
        user_result = await db_session.execute(text("""
            INSERT INTO users (username, email, phone_no)
            VALUES (:username, :email, :phone_no)
            RETURNING id
        """), {
            "username": f"rel_test_user_{uuid4().hex[:8]}",
            "email": f"rel_test_{uuid4().hex[:8]}@example.com",
            "phone_no": "+852-1234-5678"
        })
        user_id = user_result.scalar()
        
        # Create agent type and instance with new fields
        agent_type_result = await db_session.execute(text("""
            INSERT INTO agent_types (name)
            VALUES (:name)
            RETURNING id
        """), {
            "name": f"RelTestAgentType_{uuid4().hex[:8]}"
        })
        agent_type_id = agent_type_result.scalar()
        
        # Create endpoint group
        endpoint_group_result = await db_session.execute(text("""
            INSERT INTO llm_endpoint_groups (user_id, name)
            VALUES (:user_id, :name)
            RETURNING id
        """), {
            "user_id": user_id,
            "name": f"RelTestEndpointGroup_{uuid4().hex[:8]}"
        })
        endpoint_group_id = endpoint_group_result.scalar()
        
        agent_result = await db_session.execute(text("""
            INSERT INTO agent_instances (
                agent_type_id, user_id, endpoint_group_id, agent_id, phone_no
            ) VALUES (
                :agent_type_id, :user_id, :endpoint_group_id, :agent_id, :phone_no
            )
            RETURNING id
        """), {
            "agent_type_id": agent_type_id,
            "user_id": user_id,
            "endpoint_group_id": endpoint_group_id,
            "agent_id": f"rel_agent_{uuid4().hex[:8]}",
            "phone_no": "+852-8765-4321"
        })
        agent_instance_id = agent_result.scalar()
        
        # Create MCP client
        mcp_client_result = await db_session.execute(text("""
            INSERT INTO mcp_clients (user_id, name, protocol, base_url, status)
            VALUES (:user_id, :name, 'http', 'https://mcp.example.com', 'connected')
            RETURNING id
        """), {
            "user_id": user_id,
            "name": "RelTest MCP Client"
        })
        mcp_client_id = mcp_client_result.scalar()
        
        # Create tool
        tool_result = await db_session.execute(text("""
            INSERT INTO tools (name)
            VALUES (:name)
            RETURNING id
        """), {
            "name": f"rel_test_tool_{uuid4().hex[:8]}"
        })
        tool_id = tool_result.scalar()
        
        # Create MCP tool
        mcp_tool_result = await db_session.execute(text("""
            INSERT INTO mcp_tools (mcp_client_id, tool_id, mcp_tool_name)
            VALUES (:mcp_client_id, :tool_id, :mcp_tool_name)
            RETURNING id
        """), {
            "mcp_client_id": mcp_client_id,
            "tool_id": tool_id,
            "mcp_tool_name": "rel_test_tool"
        })
        mcp_tool_id = mcp_tool_result.scalar()
        
        # Create memory block
        memory_result = await db_session.execute(text("""
            INSERT INTO memory_blocks (agent_instance_id, memory_type, content)
            VALUES (:agent_instance_id, 'IDENTITY', 'Test identity memory')
            RETURNING id
        """), {
            "agent_instance_id": agent_instance_id
        })
        memory_id = memory_result.scalar()
        
        await db_session.commit()
        
        return {
            "user_id": user_id,
            "agent_instance_id": agent_instance_id,
            "endpoint_group_id": endpoint_group_id,
            "mcp_client_id": mcp_client_id,
            "mcp_tool_id": mcp_tool_id,
            "memory_id": memory_id,
            "tool_id": tool_id
        }
    
    async def test_user_agent_endpoint_join(self, db_session: AsyncSession, setup_relationship_test_data):
        """Test join query across users -> agent_instances -> llm_endpoint_groups."""
        data = setup_relationship_test_data
        
        result = await db_session.execute(text("""
            SELECT 
                u.username,
                u.phone_no as user_phone,
                ai.agent_id,
                ai.phone_no as agent_phone,
                eg.name as endpoint_group_name
            FROM users u
            JOIN agent_instances ai ON u.id = ai.user_id
            LEFT JOIN llm_endpoint_groups eg ON ai.endpoint_group_id = eg.id
            WHERE u.id = :user_id
        """), {"user_id": data["user_id"]})
        row = result.fetchone()
        
        assert row is not None
        assert row.user_phone == "+852-1234-5678"
        assert row.agent_phone == "+852-8765-4321"
        assert row.endpoint_group_name is not None
    
    async def test_mcp_client_tools_join(self, db_session: AsyncSession, setup_relationship_test_data):
        """Test join query across mcp_clients -> mcp_tools -> tools."""
        data = setup_relationship_test_data
        
        result = await db_session.execute(text("""
            SELECT 
                mc.name as client_name,
                mt.mcp_tool_name,
                t.name as tool_name
            FROM mcp_clients mc
            JOIN mcp_tools mt ON mc.id = mt.mcp_client_id
            JOIN tools t ON mt.tool_id = t.id
            WHERE mc.id = :mcp_client_id
        """), {"mcp_client_id": data["mcp_client_id"]})
        row = result.fetchone()
        
        assert row is not None
        assert row.client_name == "RelTest MCP Client"
        assert row.mcp_tool_name == "rel_test_tool"
    
    async def test_full_mcp_stack_join(self, db_session: AsyncSession, setup_relationship_test_data):
        """Test complex join across users -> mcp_clients -> mcp_tools -> tools."""
        data = setup_relationship_test_data
        
        result = await db_session.execute(text("""
            SELECT 
                u.username,
                u.phone_no,
                mc.name as mcp_client_name,
                mc.protocol,
                mt.mcp_tool_name,
                t.name as underlying_tool_name
            FROM users u
            JOIN mcp_clients mc ON u.id = mc.user_id
            JOIN mcp_tools mt ON mc.id = mt.mcp_client_id
            JOIN tools t ON mt.tool_id = t.id
            WHERE u.id = :user_id
        """), {"user_id": data["user_id"]})
        row = result.fetchone()
        
        assert row is not None
        assert row.phone_no == "+852-1234-5678"
        assert row.protocol == "http"
        assert row.underlying_tool_name is not None


class TestExistingFunctionalityCompatibility:
    """Test that existing functionality still works with new schema."""
    
    async def test_existing_user_crud(self, db_session: AsyncSession):
        """Test existing user CRUD operations still work."""
        user = User(
            username=f"compat_user_{uuid4().hex[:8]}",
            email=f"compat_{uuid4().hex[:8]}@example.com",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        # Update
        user.username = f"updated_{user.username}"
        await db_session.commit()
        
        # Query
        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched = result.scalar_one()
        
        assert fetched.username.startswith("updated_")
    
    async def test_existing_agent_crud(self, db_session: AsyncSession):
        """Test existing agent CRUD operations still work."""
        # Create user first
        user = User(
            username=f"compat_agent_user_{uuid4().hex[:8]}",
            email=f"compat_agent_{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.commit()
        
        # Create agent type
        agent_type = AgentType(
            name=f"CompatAgentType_{uuid4().hex[:8]}",
            description="Compatibility test agent type",
        )
        db_session.add(agent_type)
        await db_session.commit()
        
        # Create agent instance
        agent = AgentInstance(
            agent_type_id=agent_type.id,
            user_id=user.id,
            name="Compat Test Agent",
            status="idle",
            config={"compat": True},
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        
        assert agent.id is not None
        assert agent.config == {"compat": True}
    
    async def test_existing_tables_still_queryable(self, db_session: AsyncSession):
        """Test that existing tables can still be queried normally."""
        # Test various existing tables
        tables_to_test = [
            "users",
            "agent_types",
            "agent_instances",
            "tools",
            "tasks",
            "task_queue",
            "collaboration_sessions",
            "audit.audit_log"
        ]
        
        for table in tables_to_test:
            result = await db_session.execute(text(f"""
                SELECT COUNT(*) as count FROM {table}
            """))
            row = result.fetchone()
            assert row is not None, f"Failed to query table: {table}"


# Run with: python -m pytest tests/db/test_new_schema_integration.py -v
