# pyright: reportMissingImports=false
"""
Tests for TokenUsageDAO database operations.

This module tests CRUD operations for TokenUsageDAO following the DAO pattern.
Uses the new entity/dto/dao architecture.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession
from db.dto.token_usage_dto import (
    TokenUsageBase,
    TokenUsageCreate,
    TokenUsageUpdate,
    TokenUsage,
)
from db.dao.token_usage_dao import TokenUsageDAO
from db.entity.token_usage_entity import TokenUsage as TokenUsageEntity
from db.entity.user_entity import User as UserEntity, APIKey as APIKeyEntity
from db.entity.agent_entity import AgentType as AgentTypeEntity, AgentInstance as AgentInstanceEntity
from db.dto.user_dto import UserCreate
from db.dao.user_dao import UserDAO


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
async def sample_user(db_session: AsyncSession) -> UserEntity:
    """Create a sample user for testing."""
    user_create = UserCreate(
        username=f"tokenuser_{uuid4().hex[:8]}",
        email=f"token_{uuid4().hex[:8]}@example.com",
    )
    user_dto = await UserDAO.create(user_create, session=db_session)
    
    # Fetch the entity for relationship purposes
    from sqlalchemy import select
    result = await db_session.execute(
        select(UserEntity).where(UserEntity.id == user_dto.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def sample_agent_type(db_session: AsyncSession):
    """Create a sample agent type for testing."""
    from sqlalchemy import text
    
    # Insert agent type directly since we don't have AgentTypeDAO yet
    agent_type_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO agent_types (id, name, description, is_active, created_at, updated_at)
            VALUES (:id, :name, :description, true, now(), now())
        """),
        {"id": agent_type_id, "name": f"test_type_{uuid4().hex[:8]}", "description": "Test agent type"}
    )
    await db_session.commit()
    return agent_type_id


@pytest_asyncio.fixture
async def sample_agent_instance(
    db_session: AsyncSession, sample_user: UserEntity, sample_agent_type
) -> UUID:
    """Create a sample agent instance for testing."""
    from sqlalchemy import text
    
    agent_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO agent_instances (id, agent_type_id, user_id, status, created_at, updated_at)
            VALUES (:id, :agent_type_id, :user_id, 'idle', now(), now())
        """),
        {"id": agent_id, "agent_type_id": sample_agent_type, "user_id": sample_user.id}
    )
    await db_session.commit()
    return agent_id


@pytest_asyncio.fixture
async def clean_token_usage_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean token_usage table before and after tests."""
    await db_session.execute(delete(TokenUsageEntity))
    await db_session.commit()
    
    yield
    
    await db_session.rollback()
    await db_session.execute(delete(TokenUsageEntity))
    await db_session.commit()


class TestTokenUsageDAOCreate:
    """Test create operations for TokenUsageDAO."""
    
    async def test_create_token_usage_with_all_fields(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test creating a token usage record with all fields."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-123",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        assert created is not None
        assert created.id is not None
        assert isinstance(created.id, UUID)
        assert created.user_id == sample_user.id
        assert created.agent_id == sample_agent_instance
        assert created.session_id == "session-123"
        assert created.model_name == "gpt-4"
        assert created.input_tokens == 100
        assert created.output_tokens == 50
        assert created.total_tokens == 150
        assert created.estimated_cost_usd == Decimal("0.004500")
        assert created.created_at is not None
        assert isinstance(created.created_at, datetime)
    
    async def test_create_token_usage_returns_dto(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that create returns a TokenUsage DTO."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-dto",
            model_name="claude-3",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            estimated_cost_usd=Decimal("0.009000"),
        )
        
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        assert isinstance(created, TokenUsage)
    
    async def test_create_multiple_records_same_session(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test creating multiple records with same session_id."""
        for i in range(3):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id="shared-session",
                model_name="gpt-4",
                input_tokens=100 * (i + 1),
                output_tokens=50 * (i + 1),
                total_tokens=150 * (i + 1),
                estimated_cost_usd=Decimal("0.004500") * (i + 1),
            )
            await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        records = await TokenUsageDAO.get_by_session_id("shared-session", session=db_session)
        assert len(records) == 3


class TestTokenUsageDAOGetById:
    """Test get_by_id operations for TokenUsageDAO."""
    
    async def test_get_by_id_returns_token_usage(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test retrieving a token usage record by ID."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-get",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        fetched = await TokenUsageDAO.get_by_id(created.id, session=db_session)
        
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.session_id == "session-get"
        assert fetched.model_name == "gpt-4"
    
    async def test_get_by_id_nonexistent_returns_none(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that get_by_id returns None for nonexistent ID."""
        result = await TokenUsageDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_returns_dto(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that get_by_id returns a TokenUsage DTO."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-dto-get",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        fetched = await TokenUsageDAO.get_by_id(created.id, session=db_session)
        
        assert isinstance(fetched, TokenUsage)


class TestTokenUsageDAOGetByUserId:
    """Test get_by_user_id operations for TokenUsageDAO."""
    
    async def test_get_by_user_id_returns_records(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test retrieving token usage records by user_id."""
        for i in range(3):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id=f"session-user-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=Decimal("0.004500"),
            )
            await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        records = await TokenUsageDAO.get_by_user_id(sample_user.id, session=db_session)
        
        assert len(records) == 3
        for record in records:
            assert record.user_id == sample_user.id
    
    async def test_get_by_user_id_no_records_returns_empty(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that get_by_user_id returns empty list for user with no records."""
        records = await TokenUsageDAO.get_by_user_id(uuid4(), session=db_session)
        
        assert records == []


class TestTokenUsageDAOGetBySessionId:
    """Test get_by_session_id operations for TokenUsageDAO."""
    
    async def test_get_by_session_id_returns_records(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test retrieving token usage records by session_id."""
        for i in range(2):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id="target-session",
                model_name="gpt-4",
                input_tokens=100 * (i + 1),
                output_tokens=50 * (i + 1),
                total_tokens=150 * (i + 1),
                estimated_cost_usd=Decimal("0.004500") * (i + 1),
            )
            await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        records = await TokenUsageDAO.get_by_session_id("target-session", session=db_session)
        
        assert len(records) == 2
        for record in records:
            assert record.session_id == "target-session"
    
    async def test_get_by_session_id_no_records_returns_empty(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that get_by_session_id returns empty list for nonexistent session."""
        records = await TokenUsageDAO.get_by_session_id("nonexistent-session", session=db_session)
        
        assert records == []


class TestTokenUsageDAOGetAll:
    """Test get_all operations for TokenUsageDAO."""
    
    async def test_get_all_returns_all_records(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test retrieving all token usage records."""
        for i in range(3):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id=f"session-all-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=Decimal("0.004500"),
            )
            await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        records = await TokenUsageDAO.get_all(session=db_session)
        
        assert len(records) == 3
    
    async def test_get_all_empty_table_returns_empty_list(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that get_all returns empty list when no records exist."""
        records = await TokenUsageDAO.get_all(session=db_session)
        
        assert records == []
    
    async def test_get_all_with_pagination(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test get_all with limit and offset."""
        for i in range(5):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id=f"session-page-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=Decimal("0.004500"),
            )
            await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        # Test limit
        records_limited = await TokenUsageDAO.get_all(limit=2, session=db_session)
        assert len(records_limited) == 2
        
        # Test offset
        records_offset = await TokenUsageDAO.get_all(limit=2, offset=2, session=db_session)
        assert len(records_offset) == 2
        
        # Verify different records returned
        ids_limited = {r.id for r in records_limited}
        ids_offset = {r.id for r in records_offset}
        assert ids_limited.isdisjoint(ids_offset)
    
    async def test_get_all_returns_dtos(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that get_all returns TokenUsage DTOs."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-dto-list",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        records = await TokenUsageDAO.get_all(session=db_session)
        
        assert len(records) == 1
        assert isinstance(records[0], TokenUsage)


class TestTokenUsageDAOUpdate:
    """Test update operations for TokenUsageDAO."""
    
    async def test_update_token_usage_is_not_supported(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that update returns None (token usage records are immutable)."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-no-update",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        # Token usage records are typically immutable (audit trail)
        # Update should return None or raise NotImplementedError
        result = await TokenUsageDAO.update(
            TokenUsageUpdate(id=created.id, total_tokens=999),
            session=db_session
        )
        
        # Verify the record was NOT updated
        fetched = await TokenUsageDAO.get_by_id(created.id, session=db_session)
        assert fetched.total_tokens == 150  # Original value


class TestTokenUsageDAODelete:
    """Test delete operations for TokenUsageDAO."""
    
    async def test_delete_existing_record(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test deleting an existing token usage record."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-delete",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        result = await TokenUsageDAO.delete(created.id, session=db_session)
        
        assert result is True
        
        # Verify record is deleted
        fetched = await TokenUsageDAO.get_by_id(created.id, session=db_session)
        assert fetched is None
    
    async def test_delete_nonexistent_returns_false(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that deleting a nonexistent record returns False."""
        result = await TokenUsageDAO.delete(uuid4(), session=db_session)
        
        assert result is False


class TestTokenUsageDAOExists:
    """Test exists operations for TokenUsageDAO."""
    
    async def test_exists_returns_true_for_existing_record(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that exists returns True for existing record."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-exists",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        result = await TokenUsageDAO.exists(created.id, session=db_session)
        
        assert result is True
    
    async def test_exists_returns_false_for_nonexistent(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that exists returns False for nonexistent record."""
        result = await TokenUsageDAO.exists(uuid4(), session=db_session)
        
        assert result is False


class TestTokenUsageDAOCount:
    """Test count operations for TokenUsageDAO."""
    
    async def test_count_returns_correct_number(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that count returns the correct number of records."""
        for i in range(3):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id=f"session-count-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=Decimal("0.004500"),
            )
            await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        count = await TokenUsageDAO.count(session=db_session)
        
        assert count == 3
    
    async def test_count_empty_table_returns_zero(
        self,
        db_session: AsyncSession,
        clean_token_usage_table: None,
    ):
        """Test that count returns 0 for empty table."""
        count = await TokenUsageDAO.count(session=db_session)
        
        assert count == 0


class TestTokenUsageDAOCostPrecision:
    """Test that estimated_cost_usd maintains Decimal precision."""
    
    async def test_cost_precision_maintained(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that cost maintains 6 decimal precision."""
        costs = [
            Decimal("0.000001"),  # Minimum precision
            Decimal("0.123456"),  # Full precision
            Decimal("99.999999"),  # Large with precision
        ]
        
        for i, cost in enumerate(costs):
            token_usage_create = TokenUsageCreate(
                user_id=sample_user.id,
                agent_id=sample_agent_instance,
                session_id=f"session-precision-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=cost,
            )
            
            created = await TokenUsageDAO.create(token_usage_create, session=db_session)
            
            assert created.estimated_cost_usd == cost


class TestTokenUsageDAOTimestamps:
    """Test timestamp handling."""
    
    async def test_created_at_is_utc(
        self,
        db_session: AsyncSession,
        sample_user: UserEntity,
        sample_agent_instance: UUID,
        clean_token_usage_table: None,
    ):
        """Test that created_at is timezone-aware UTC."""
        token_usage_create = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance,
            session_id="session-timestamp",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        created = await TokenUsageDAO.create(token_usage_create, session=db_session)
        
        assert created.created_at.tzinfo is not None
        # Should be UTC (or equivalent)
        assert created.created_at.utcoffset().total_seconds() == 0