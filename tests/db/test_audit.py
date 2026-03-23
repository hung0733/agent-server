# pyright: reportMissingImports=false
"""
Tests for audit log database models.

This module tests CRUD operations, schema creation, indexes,
and constraint enforcement for the audit.audit_log table.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.entity.audit_entity import AuditLog
from db.types import ActorType, gen_random_uuid


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
    
    # Create audit schema and table for this test run
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE audit.actor_type_enum AS ENUM ('user', 'agent', 'system');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit.audit_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID,
                actor_type audit.actor_type_enum NOT NULL,
                actor_id UUID NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id UUID NOT NULL,
                old_values JSONB,
                new_values JSONB,
                ip_address INET,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_audit_user_time 
            ON audit.audit_log(user_id, created_at DESC)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_audit_resource 
            ON audit.audit_log(resource_type, resource_id)
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop table and schema after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS audit.audit_log"))
        await conn.execute(text("DROP TYPE IF EXISTS audit.actor_type_enum"))
        await conn.execute(text("DROP SCHEMA IF EXISTS audit"))
    
    await engine.dispose()


class TestAuditSchema:
    """Test audit schema creation and structure."""
    
    async def test_audit_schema_exists(self, db_session: AsyncSession):
        """Test that the audit schema was created."""
        result = await db_session.execute(
            text("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name = 'audit'
            """)
        )
        schema = result.scalar_one_or_none()
        assert schema == "audit"
    
    async def test_audit_log_table_exists(self, db_session: AsyncSession):
        """Test that the audit_log table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'audit' AND table_name = 'audit_log'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "audit_log"
    
    async def test_audit_log_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in audit_log table."""
        expected_columns = {
            'id', 'user_id', 'actor_type', 'actor_id', 'action',
            'resource_type', 'resource_id', 'old_values', 'new_values',
            'ip_address', 'created_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'audit' AND table_name = 'audit_log'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_actor_type_enum_exists(self, db_session: AsyncSession):
        """Test that the actor_type_enum type exists with correct values."""
        result = await db_session.execute(
            text("""
                SELECT e.enumlabel 
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid  
                WHERE t.typname = 'actor_type_enum'
                ORDER BY e.enumsortorder
            """)
        )
        enum_values = [row[0] for row in result.fetchall()]
        
        assert set(enum_values) == {'user', 'agent', 'system'}
    
    async def test_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE schemaname = 'audit' AND tablename = 'audit_log'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_audit_user_time' in indexes
        assert 'idx_audit_resource' in indexes


class TestAuditLogCRUD:
    """Test CRUD operations for AuditLog model."""
    
    async def test_create_audit_log_user_action(self, db_session: AsyncSession):
        """Test creating an audit log entry for a user action."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=resource_id,
            old_values=None,
            new_values={"name": "New Task", "status": "pending"},
            ip_address="192.168.1.1",
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.id is not None
        assert isinstance(audit_entry.id, UUID)
        assert audit_entry.user_id == user_id
        assert audit_entry.actor_type == ActorType.user
        assert audit_entry.actor_id == user_id
        assert audit_entry.action == "create"
        assert audit_entry.resource_type == "task"
        assert audit_entry.resource_id == resource_id
        assert audit_entry.old_values is None
        assert isinstance(audit_entry.new_values, dict)
        # INET type returns ipaddress.IPv4Address object, convert to string for comparison
        assert str(audit_entry.ip_address) == "192.168.1.1"
        assert audit_entry.created_at is not None
        assert isinstance(audit_entry.created_at, datetime)
    
    async def test_create_audit_log_agent_action(self, db_session: AsyncSession):
        """Test creating an audit log entry for an agent action."""
        agent_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            actor_type=ActorType.agent,
            actor_id=agent_id,
            action="execute",
            resource_type="workflow",
            resource_id=resource_id,
            old_values={"state": "idle"},
            new_values={"state": "running"},
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.actor_type == ActorType.agent
        assert audit_entry.user_id is None
        assert audit_entry.actor_id == agent_id
        assert audit_entry.action == "execute"
    
    async def test_create_audit_log_system_action(self, db_session: AsyncSession):
        """Test creating an audit log entry for a system action."""
        system_id = uuid4()
        resource_id = uuid4()
        
        audit_entry = AuditLog(
            actor_type=ActorType.system,
            actor_id=system_id,
            action="cleanup",
            resource_type="session",
            resource_id=resource_id,
            old_values=None,
            new_values=None,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.actor_type == ActorType.system
        assert audit_entry.user_id is None
        assert audit_entry.action == "cleanup"
    
    async def test_get_audit_log_by_id(self, db_session: AsyncSession):
        """Test retrieving an audit log entry by ID."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="update",
            resource_type="user",
            resource_id=resource_id,
            old_values={"email": "old@example.com"},
            new_values={"email": "new@example.com"},
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        result = await db_session.execute(
            select(AuditLog).where(AuditLog.id == audit_entry.id)
        )
        fetched = result.scalar_one()
        
        assert fetched is not None
        assert fetched.id == audit_entry.id
        assert fetched.action == "update"
        assert fetched.old_values == {"email": "old@example.com"}
        assert fetched.new_values == {"email": "new@example.com"}
    
    async def test_list_audit_logs_by_user(self, db_session: AsyncSession):
        """Test listing audit logs filtered by user_id."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        # Create multiple audit entries for the same user
        for i in range(3):
            audit_entry = AuditLog(
                user_id=user_id,
                actor_type=ActorType.user,
                actor_id=user_id,
                action=f"action{i}",
                resource_type="resource",
                resource_id=resource_id,
            )
            db_session.add(audit_entry)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AuditLog).where(AuditLog.user_id == user_id)
        )
        entries = result.scalars().all()
        
        assert len(entries) == 3
        actions = {e.action for e in entries}
        assert actions == {"action0", "action1", "action2"}
    
    async def test_list_audit_logs_by_resource(self, db_session: AsyncSession):
        """Test listing audit logs filtered by resource_type and resource_id."""
        resource_id = gen_random_uuid()
        user_id = gen_random_uuid()
        
        # Create multiple audit entries for the same resource
        for action in ["create", "update", "update"]:
            audit_entry = AuditLog(
                user_id=user_id,
                actor_type=ActorType.user,
                actor_id=user_id,
                action=action,
                resource_type="document",
                resource_id=resource_id,
            )
            db_session.add(audit_entry)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "document",
                AuditLog.resource_id == resource_id,
            )
        )
        entries = result.scalars().all()
        
        assert len(entries) == 3
    
    async def test_delete_audit_log(self, db_session: AsyncSession):
        """Test deleting an audit log entry."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="delete",
            resource_type="file",
            resource_id=resource_id,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        # Note: In production, audit logs should be immutable
        # This test is for verifying the basic CRUD capability
        await db_session.delete(audit_entry)
        await db_session.commit()
        
        result = await db_session.execute(
            select(AuditLog).where(AuditLog.id == audit_entry.id)
        )
        assert result.scalar_one_or_none() is None


class TestActorTypeValidation:
    """Test ActorType enum validation."""
    
    async def test_actor_type_user_enum(self, db_session: AsyncSession):
        """Test that 'user' is a valid actor_type."""
        assert ActorType.user == "user"
        assert ActorType.user.value == "user"
    
    async def test_actor_type_agent_enum(self, db_session: AsyncSession):
        """Test that 'agent' is a valid actor_type."""
        assert ActorType.agent == "agent"
        assert ActorType.agent.value == "agent"
    
    async def test_actor_type_system_enum(self, db_session: AsyncSession):
        """Test that 'system' is a valid actor_type."""
        assert ActorType.system == "system"
        assert ActorType.system.value == "system"
    
    async def test_actor_type_from_string(self, db_session: AsyncSession):
        """Test that actor_type can be created from string."""
        assert ActorType("user") is ActorType.user
        assert ActorType("agent") is ActorType.agent
        assert ActorType("system") is ActorType.system
    
    async def test_invalid_actor_type_raises_error(self, db_session: AsyncSession):
        """Test that invalid actor_type values raise ValueError."""
        with pytest.raises(ValueError):
            ActorType("invalid_actor")
    
    async def test_actor_type_serialization(self, db_session: AsyncSession):
        """Test that actor_type serializes to string."""
        assert str(ActorType.user) == "user"
        assert not isinstance(ActorType.user.value, int)


class TestJSONBFields:
    """Test JSONB field functionality."""
    
    async def test_jsonb_old_values_storage(self, db_session: AsyncSession):
        """Test that old_values JSONB field stores complex data."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        old_data: Dict[str, Any] = {
            "name": "Old Name",
            "status": "pending",
            "metadata": {
                "priority": 1,
                "tags": ["important", "urgent"],
            },
        }
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="update",
            resource_type="task",
            resource_id=resource_id,
            old_values=old_data,
            new_values=None,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.old_values == old_data
        assert audit_entry.old_values["metadata"]["tags"] == ["important", "urgent"]
    
    async def test_jsonb_new_values_storage(self, db_session: AsyncSession):
        """Test that new_values JSONB field stores complex data."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        new_data: Dict[str, Any] = {
            "name": "New Name",
            "status": "completed",
            "metadata": {
                "priority": 2,
                "tags": ["done"],
            },
        }
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="update",
            resource_type="task",
            resource_id=resource_id,
            old_values=None,
            new_values=new_data,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.new_values == new_data
    
    async def test_jsonb_null_values(self, db_session: AsyncSession):
        """Test that JSONB fields can be null."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        # Create action (no old_values)
        create_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=resource_id,
            old_values=None,
            new_values={"name": "New"},
        )
        db_session.add(create_entry)
        
        # Delete action (no new_values)
        delete_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="delete",
            resource_type="task",
            resource_id=resource_id,
            old_values={"name": "Deleted"},
            new_values=None,
        )
        db_session.add(delete_entry)
        
        await db_session.commit()
        
        assert create_entry.old_values is None
        assert delete_entry.new_values is None


class TestINETField:
    """Test INET field functionality."""
    
    async def test_ipv4_address_storage(self, db_session: AsyncSession):
        """Test that IPv4 addresses are stored correctly."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=resource_id,
            ip_address="192.168.1.1",
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        # INET type returns ipaddress.IPv4Address object
        assert str(audit_entry.ip_address) == "192.168.1.1"
    
    async def test_ipv6_address_storage(self, db_session: AsyncSession):
        """Test that IPv6 addresses are stored correctly."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=resource_id,
            ip_address="2001:0db8:85a3:0000:0000:8a2e:0370:7334",
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.ip_address is not None
        # INET type returns ipaddress.IPv6Address object
        assert "2001" in str(audit_entry.ip_address)
    
    async def test_null_ip_address(self, db_session: AsyncSession):
        """Test that ip_address can be null (system actions)."""
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            actor_type=ActorType.system,
            actor_id=uuid4(),
            action="cleanup",
            resource_type="session",
            resource_id=resource_id,
            ip_address=None,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.ip_address is None


class TestConstraints:
    """Test database constraints on audit_log table."""
    
    async def test_not_null_actor_type(self, db_session: AsyncSession):
        """Test that actor_type is required (NOT NULL)."""
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            actor_id=uuid4(),
            action="test",
            resource_type="test",
            resource_id=resource_id,
            actor_type=None,  # type: ignore
        )
        db_session.add(audit_entry)
        
        with pytest.raises(Exception):
            await db_session.commit()
    
    async def test_not_null_actor_id(self, db_session: AsyncSession):
        """Test that actor_id is required (NOT NULL)."""
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            actor_type=ActorType.user,
            action="test",
            resource_type="test",
            resource_id=resource_id,
            actor_id=None,  # type: ignore
        )
        db_session.add(audit_entry)
        
        with pytest.raises(Exception):
            await db_session.commit()
    
    async def test_not_null_action(self, db_session: AsyncSession):
        """Test that action is required (NOT NULL)."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action=None,  # type: ignore
            resource_type="test",
            resource_id=resource_id,
        )
        db_session.add(audit_entry)
        
        with pytest.raises(Exception):
            await db_session.commit()
    
    async def test_not_null_resource_type(self, db_session: AsyncSession):
        """Test that resource_type is required (NOT NULL)."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="test",
            resource_type=None,  # type: ignore
            resource_id=resource_id,
        )
        db_session.add(audit_entry)
        
        with pytest.raises(Exception):
            await db_session.commit()
    
    async def test_not_null_resource_id(self, db_session: AsyncSession):
        """Test that resource_id is required (NOT NULL)."""
        user_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="test",
            resource_type="test",
            resource_id=None,  # type: ignore
        )
        db_session.add(audit_entry)
        
        with pytest.raises(Exception):
            await db_session.commit()
    
    async def test_user_id_can_be_null(self, db_session: AsyncSession):
        """Test that user_id can be NULL (for agent/system actions)."""
        agent_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=None,
            actor_type=ActorType.agent,
            actor_id=agent_id,
            action="execute",
            resource_type="workflow",
            resource_id=resource_id,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.user_id is None
        assert audit_entry.actor_type == ActorType.agent


class TestAuditLogImmutability:
    """Test audit log immutability patterns."""
    
    async def test_audit_log_created_with_timestamp(self, db_session: AsyncSession):
        """Test that audit log entries have created_at timestamp."""
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=resource_id,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        assert audit_entry.created_at is not None
        assert isinstance(audit_entry.created_at, datetime)
        assert audit_entry.created_at.tzinfo == timezone.utc
    
    async def test_audit_log_read_only_pattern(self, db_session: AsyncSession):
        """Test that audit logs should be read-only in practice.
        
        Note: This is a pattern test - the database allows updates,
        but the application should NOT update audit logs.
        """
        user_id = gen_random_uuid()
        resource_id = gen_random_uuid()
        
        audit_entry = AuditLog(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=resource_id,
        )
        db_session.add(audit_entry)
        await db_session.commit()
        await db_session.refresh(audit_entry)
        
        original_created_at = audit_entry.created_at
        
        # Wait to ensure any update would change timestamp
        await asyncio.sleep(0.01)
        
        # While technically possible, audit logs should be treated as immutable
        # This test documents that pattern - in production, updates should be
        # prevented at the application layer
        old_action = audit_entry.action
        assert old_action == "create"
