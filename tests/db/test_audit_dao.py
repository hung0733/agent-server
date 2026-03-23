# pyright: reportMissingImports=false
"""
Tests for AuditLogDAO database operations.

This module tests CRUD operations for AuditLogDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.dto.audit_dto import AuditLogCreate, AuditLog
from db.dao.audit_dao import AuditLogDAO
from db.entity.audit_entity import AuditLog as AuditLogEntity
from db.types import ActorType


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
        await session.rollback()
    
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_audit_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean audit_log table before and after tests."""
    await db_session.execute(delete(AuditLogEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(AuditLogEntity))
    await db_session.commit()


class TestAuditLogDAOCreate:
    """Test create operations for AuditLogDAO."""
    
    async def test_create_audit_log_user_action(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test creating an audit log entry for a user action."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
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
        
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log is not None
        assert created_log.id is not None
        assert isinstance(created_log.id, UUID)
        assert created_log.user_id == user_id
        assert created_log.actor_type == ActorType.user
        assert created_log.actor_id == user_id
        assert created_log.action == "create"
        assert created_log.resource_type == "task"
        assert created_log.resource_id == resource_id
        assert created_log.old_values is None
        assert created_log.new_values == {"name": "New Task", "status": "pending"}
        assert created_log.created_at is not None
        assert isinstance(created_log.created_at, datetime)
    
    async def test_create_audit_log_agent_action(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test creating an audit log entry for an agent action."""
        agent_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.agent,
            actor_id=agent_id,
            action="execute",
            resource_type="workflow",
            resource_id=resource_id,
            old_values={"state": "idle"},
            new_values={"state": "running"},
        )
        
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log is not None
        assert created_log.actor_type == ActorType.agent
        assert created_log.user_id is None
        assert created_log.actor_id == agent_id
        assert created_log.action == "execute"
    
    async def test_create_audit_log_system_action(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test creating an audit log entry for a system action."""
        system_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.system,
            actor_id=system_id,
            action="cleanup",
            resource_type="session",
            resource_id=resource_id,
        )
        
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log is not None
        assert created_log.actor_type == ActorType.system
        assert created_log.user_id is None
        assert created_log.action == "cleanup"
    
    async def test_create_returns_dto(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that create returns an AuditLog DTO, not an entity."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.user,
            actor_id=user_id,
            action="test",
            resource_type="test",
            resource_id=resource_id,
        )
        
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert isinstance(created_log, AuditLog)


class TestAuditLogDAOGetById:
    """Test get_by_id operations for AuditLogDAO."""
    
    async def test_get_by_id_returns_audit_log(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test retrieving an audit log by ID."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="update",
            resource_type="user",
            resource_id=resource_id,
            old_values={"email": "old@example.com"},
            new_values={"email": "new@example.com"},
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        fetched_log = await AuditLogDAO.get_by_id(created_log.id, session=db_session)
        
        assert fetched_log is not None
        assert fetched_log.id == created_log.id
        assert fetched_log.action == "update"
        assert fetched_log.old_values == {"email": "old@example.com"}
        assert fetched_log.new_values == {"email": "new@example.com"}
    
    async def test_get_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        nonexistent_id = uuid4()
        
        result = await AuditLogDAO.get_by_id(nonexistent_id, session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that get_by_id returns an AuditLog DTO."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.user,
            actor_id=user_id,
            action="test",
            resource_type="test",
            resource_id=resource_id,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        fetched_log = await AuditLogDAO.get_by_id(created_log.id, session=db_session)
        
        assert isinstance(fetched_log, AuditLog)


class TestAuditLogDAOGetAll:
    """Test get_all operations for AuditLogDAO."""
    
    async def test_get_all_returns_all_logs(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test retrieving all audit logs."""
        user_id = uuid4()
        resource_id = uuid4()
        
        for i in range(3):
            audit_create = AuditLogCreate(
                user_id=user_id,
                actor_type=ActorType.user,
                actor_id=user_id,
                action=f"action{i}",
                resource_type="resource",
                resource_id=resource_id,
            )
            await AuditLogDAO.create(audit_create, session=db_session)
        
        logs = await AuditLogDAO.get_all(session=db_session)
        
        assert len(logs) == 3
        actions = {log.action for log in logs}
        assert actions == {"action0", "action1", "action2"}
    
    async def test_get_all_empty_table_returns_empty_list(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that get_all returns empty list when no logs exist."""
        logs = await AuditLogDAO.get_all(session=db_session)
        
        assert logs == []
    
    async def test_get_all_with_pagination(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test get_all with limit and offset."""
        user_id = uuid4()
        resource_id = uuid4()
        
        for i in range(5):
            audit_create = AuditLogCreate(
                actor_type=ActorType.user,
                actor_id=user_id,
                action=f"paginated{i}",
                resource_type="resource",
                resource_id=resource_id,
            )
            await AuditLogDAO.create(audit_create, session=db_session)
        
        # Test limit
        logs_limited = await AuditLogDAO.get_all(limit=2, session=db_session)
        assert len(logs_limited) == 2
        
        # Test offset
        logs_offset = await AuditLogDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(logs_offset) == 2
        
        # Verify different logs returned
        ids_limited = {log.id for log in logs_limited}
        ids_offset = {log.id for log in logs_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that get_all returns AuditLog DTOs."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.user,
            actor_id=user_id,
            action="test",
            resource_type="test",
            resource_id=resource_id,
        )
        await AuditLogDAO.create(audit_create, session=db_session)
        
        logs = await AuditLogDAO.get_all(session=db_session)
        
        assert len(logs) == 1
        assert isinstance(logs[0], AuditLog)


class TestAuditLogDAOGetByUser:
    """Test get_by_user operations for AuditLogDAO."""
    
    async def test_get_by_user_returns_logs(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test retrieving audit logs by user_id."""
        user_id = uuid4()
        other_user_id = uuid4()
        resource_id = uuid4()
        
        # Create logs for target user
        for i in range(3):
            audit_create = AuditLogCreate(
                user_id=user_id,
                actor_type=ActorType.user,
                actor_id=user_id,
                action=f"user_action{i}",
                resource_type="resource",
                resource_id=resource_id,
            )
            await AuditLogDAO.create(audit_create, session=db_session)
        
        # Create log for other user
        other_create = AuditLogCreate(
            user_id=other_user_id,
            actor_type=ActorType.user,
            actor_id=other_user_id,
            action="other_action",
            resource_type="resource",
            resource_id=resource_id,
        )
        await AuditLogDAO.create(other_create, session=db_session)
        
        logs = await AuditLogDAO.get_by_user(user_id, session=db_session)
        
        assert len(logs) == 3
        for log in logs:
            assert log.user_id == user_id
    
    async def test_get_by_user_empty_returns_empty_list(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that get_by_user returns empty list for user with no logs."""
        user_id = uuid4()
        
        logs = await AuditLogDAO.get_by_user(user_id, session=db_session)
        
        assert logs == []


class TestAuditLogDAOGetByResource:
    """Test get_by_resource operations for AuditLogDAO."""
    
    async def test_get_by_resource_returns_logs(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test retrieving audit logs by resource_type and resource_id."""
        resource_id = uuid4()
        other_resource_id = uuid4()
        user_id = uuid4()
        
        # Create logs for target resource
        for action in ["create", "update", "update"]:
            audit_create = AuditLogCreate(
                user_id=user_id,
                actor_type=ActorType.user,
                actor_id=user_id,
                action=action,
                resource_type="document",
                resource_id=resource_id,
            )
            await AuditLogDAO.create(audit_create, session=db_session)
        
        # Create log for other resource
        other_create = AuditLogCreate(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="document",
            resource_id=other_resource_id,
        )
        await AuditLogDAO.create(other_create, session=db_session)
        
        logs = await AuditLogDAO.get_by_resource(
            resource_type="document",
            resource_id=resource_id,
            session=db_session,
        )
        
        assert len(logs) == 3
        for log in logs:
            assert log.resource_type == "document"
            assert log.resource_id == resource_id
    
    async def test_get_by_resource_empty_returns_empty_list(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that get_by_resource returns empty list for nonexistent resource."""
        resource_id = uuid4()
        
        logs = await AuditLogDAO.get_by_resource(
            resource_type="nonexistent",
            resource_id=resource_id,
            session=db_session,
        )
        
        assert logs == []


class TestAuditLogDAOCount:
    """Test count operations for AuditLogDAO."""
    
    async def test_count_returns_correct_number(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that count returns the correct number of audit logs."""
        user_id = uuid4()
        resource_id = uuid4()
        
        for i in range(3):
            audit_create = AuditLogCreate(
                actor_type=ActorType.user,
                actor_id=user_id,
                action=f"count{i}",
                resource_type="resource",
                resource_id=resource_id,
            )
            await AuditLogDAO.create(audit_create, session=db_session)
        
        count = await AuditLogDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that count returns 0 for empty table."""
        count = await AuditLogDAO.count(session=db_session)
        
        assert count == 0


class TestAuditLogDAOExists:
    """Test exists operations for AuditLogDAO."""
    
    async def test_exists_returns_true_for_existing_log(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that exists returns True for existing log."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.user,
            actor_id=user_id,
            action="exists_test",
            resource_type="resource",
            resource_id=resource_id,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        result = await AuditLogDAO.exists(created_log.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent_log(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that exists returns False for nonexistent log."""
        result = await AuditLogDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestAuditLogDAOJSONBFields:
    """Test JSONB field functionality."""
    
    async def test_jsonb_old_values_complex_data(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that old_values JSONB field stores complex data."""
        user_id = uuid4()
        resource_id = uuid4()
        
        old_data: Dict[str, Any] = {
            "name": "Old Name",
            "status": "pending",
            "metadata": {
                "priority": 1,
                "tags": ["important", "urgent"],
            },
        }
        
        audit_create = AuditLogCreate(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="update",
            resource_type="task",
            resource_id=resource_id,
            old_values=old_data,
            new_values=None,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log.old_values == old_data
        assert created_log.old_values["metadata"]["tags"] == ["important", "urgent"]
    
    async def test_jsonb_new_values_complex_data(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that new_values JSONB field stores complex data."""
        user_id = uuid4()
        resource_id = uuid4()
        
        new_data: Dict[str, Any] = {
            "name": "New Name",
            "status": "completed",
            "metadata": {
                "priority": 2,
                "tags": ["done"],
            },
        }
        
        audit_create = AuditLogCreate(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="update",
            resource_type="task",
            resource_id=resource_id,
            old_values=None,
            new_values=new_data,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log.new_values == new_data


class TestAuditLogDAOActorTypes:
    """Test different actor types."""
    
    async def test_user_actor_type(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test creating audit log with user actor type."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            user_id=user_id,
            actor_type=ActorType.user,
            actor_id=user_id,
            action="test",
            resource_type="resource",
            resource_id=resource_id,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log.actor_type == ActorType.user
        assert created_log.user_id == user_id
        assert created_log.actor_id == user_id
    
    async def test_agent_actor_type(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test creating audit log with agent actor type."""
        agent_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.agent,
            actor_id=agent_id,
            action="execute",
            resource_type="workflow",
            resource_id=resource_id,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log.actor_type == ActorType.agent
        assert created_log.user_id is None
        assert created_log.actor_id == agent_id
    
    async def test_system_actor_type(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test creating audit log with system actor type."""
        system_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.system,
            actor_id=system_id,
            action="cleanup",
            resource_type="session",
            resource_id=resource_id,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log.actor_type == ActorType.system
        assert created_log.user_id is None


class TestAuditLogDAOTimestamp:
    """Test timestamp functionality."""
    
    async def test_created_at_set_automatically(
        self, db_session: AsyncSession, clean_audit_table: None
    ):
        """Test that created_at is set automatically."""
        user_id = uuid4()
        resource_id = uuid4()
        
        audit_create = AuditLogCreate(
            actor_type=ActorType.user,
            actor_id=user_id,
            action="timestamp_test",
            resource_type="resource",
            resource_id=resource_id,
        )
        created_log = await AuditLogDAO.create(audit_create, session=db_session)
        
        assert created_log.created_at is not None
        assert isinstance(created_log.created_at, datetime)
        # Verify timezone is UTC
        assert created_log.created_at.tzinfo == timezone.utc