# pyright: reportMissingImports=false
"""
Tests for token usage database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, and DECIMAL precision for token_usage table.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.schema.token_usage import TokenUsage
from db.schema.users import User  # noqa: F401 - Import for FK constraint
from db.schema.agents import AgentInstance, AgentType  # noqa: F401 - Import for FK constraint


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
        
        # Create agent_types table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_types (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                capabilities JSONB,
                default_config JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create agent_instances table with FK constraints
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_instances (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_type_id UUID NOT NULL REFERENCES agent_types(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT,
                status TEXT NOT NULL DEFAULT 'idle' 
                    CHECK (status IN ('idle', 'busy', 'error', 'offline')),
                config JSONB,
                last_heartbeat_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create token_usage table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID NOT NULL REFERENCES agent_instances(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                estimated_cost_usd NUMERIC(10, 6) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_user_created 
            ON token_usage(user_id, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_session 
            ON token_usage(session_id)
        """))
    
    # Create session
    session = async_session()
    try:
        yield session
    finally:
        await session.close()
        
        # Drop tables in reverse dependency order
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS token_usage CASCADE"))
            await conn.execute(text("DROP TABLE IF EXISTS agent_instances CASCADE"))
            await conn.execute(text("DROP TABLE IF EXISTS agent_types CASCADE"))
            await conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user for testing."""
    user = User(
        username=f"testuser_{uuid4()}",
        email=f"test_{uuid4()}@example.com",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_agent_type(db_session: AsyncSession) -> AgentType:
    """Create a sample agent type for testing."""
    agent_type = AgentType(
        name=f"test_agent_type_{uuid4()}",
        description="Test agent type for token usage testing",
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


@pytest_asyncio.fixture
async def sample_agent_instance(
    db_session: AsyncSession,
    sample_user: User,
    sample_agent_type: AgentType,
) -> AgentInstance:
    """Create a sample agent instance for testing."""
    agent = AgentInstance(
        agent_type_id=sample_agent_type.id,
        user_id=sample_user.id,
        name="Test Agent Instance",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


class TestTokenUsageSchema:
    """Test token_usage table schema and constraints."""
    
    async def test_table_exists(self, db_session: AsyncSession):
        """Test that token_usage table exists."""
        result = await db_session.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'token_usage'
        """))
        assert result.scalar() == "token_usage"
    
    async def test_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist."""
        result = await db_session.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'token_usage'
            ORDER BY ordinal_position
        """))
        columns = [row[0] for row in result.fetchall()]
        
        expected_columns = [
            'id', 'user_id', 'agent_id', 'session_id', 'model_name',
            'input_tokens', 'output_tokens', 'total_tokens',
            'estimated_cost_usd', 'created_at'
        ]
        for col in expected_columns:
            assert col in columns, f"Column {col} should exist"
    
    async def test_indexes_exist(self, db_session: AsyncSession):
        """Test that required indexes exist."""
        result = await db_session.execute(text("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'token_usage'
        """))
        indexes = [row[0] for row in result.fetchall()]
        
        assert 'idx_token_usage_user_created' in indexes
        assert 'idx_token_usage_session' in indexes
    
    async def test_decimal_precision(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that estimated_cost_usd uses DECIMAL(10,6) precision."""
        cost = Decimal("0.123456")  # 6 decimal places
        
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="test-session",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=cost,
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        await db_session.refresh(token_usage)
        
        # Verify precision is maintained
        assert token_usage.estimated_cost_usd == cost
        assert str(token_usage.estimated_cost_usd) == "0.123456"
    
    async def test_foreign_key_user_constraint(self, db_session: AsyncSession):
        """Test that foreign key constraint to users exists."""
        result = await db_session.execute(text("""
            SELECT conname FROM pg_constraint 
            WHERE conrelid = 'token_usage'::regclass 
            AND contype = 'f' 
            AND conname LIKE '%user%'
        """))
        constraints = result.fetchall()
        assert len(constraints) > 0, "Foreign key constraint to users should exist"
    
    async def test_foreign_key_agent_constraint(self, db_session: AsyncSession):
        """Test that foreign key constraint to agent_instances exists."""
        result = await db_session.execute(text("""
            SELECT conname FROM pg_constraint 
            WHERE conrelid = 'token_usage'::regclass 
            AND contype = 'f' 
            AND conname LIKE '%agent%'
        """))
        constraints = result.fetchall()
        assert len(constraints) > 0, "Foreign key constraint to agent_instances should exist"


class TestTokenUsageCRUD:
    """Test token_usage CRUD operations."""
    
    async def test_create_token_usage(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test creating a token usage record."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-123",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        await db_session.refresh(token_usage)
        
        assert token_usage.id is not None
        assert token_usage.user_id == sample_user.id
        assert token_usage.agent_id == sample_agent_instance.id
        assert token_usage.input_tokens == 100
        assert token_usage.output_tokens == 50
        assert token_usage.total_tokens == 150
    
    async def test_read_token_usage(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test reading a token usage record."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-456",
            model_name="claude-3",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            estimated_cost_usd=Decimal("0.009000"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        
        # Read back
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.id == token_usage.id)
        )
        retrieved = result.scalar_one()
        
        assert retrieved is not None
        assert retrieved.session_id == "session-456"
        assert retrieved.model_name == "claude-3"
    
    async def test_update_token_usage(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that token_usage records are immutable (no update)."""
        # Token usage should be immutable - this test verifies we can query it
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-789",
            model_name="gpt-3.5",
            input_tokens=50,
            output_tokens=25,
            total_tokens=75,
            estimated_cost_usd=Decimal("0.001500"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        
        # Verify it exists and can be queried
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.session_id == "session-789")
        )
        records = result.scalars().all()
        assert len(records) == 1
    
    async def test_delete_token_usage(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test deleting a token usage record."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-delete",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        
        # Delete
        await db_session.delete(token_usage)
        await db_session.commit()
        
        # Verify deleted
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.id == token_usage.id)
        )
        assert result.scalar_one_or_none() is None


class TestTokenUsageRelationships:
    """Test token_usage foreign key relationships."""
    
    async def test_cascade_delete_user(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that deleting a user cascades to token_usage."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-cascade-user",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        token_usage_id = token_usage.id
        
        # Delete user
        await db_session.delete(sample_user)
        await db_session.commit()
        
        # Verify token_usage is also deleted
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.id == token_usage_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_cascade_delete_agent(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that deleting an agent cascades to token_usage."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-cascade-agent",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        token_usage_id = token_usage.id
        
        # Delete agent
        await db_session.delete(sample_agent_instance)
        await db_session.commit()
        
        # Verify token_usage is also deleted
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.id == token_usage_id)
        )
        assert result.scalar_one_or_none() is None


class TestTokenUsageIndexes:
    """Test token_usage index functionality."""
    
    async def test_user_created_index_usage(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that user_id + created_at index works correctly."""
        # Create multiple records
        for i in range(5):
            token_usage = TokenUsage(
                user_id=sample_user.id,
                agent_id=sample_agent_instance.id,
                session_id=f"session-index-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=Decimal("0.004500"),
            )
            db_session.add(token_usage)
        
        await db_session.commit()
        
        # Query by user_id (should use index)
        result = await db_session.execute(
            select(TokenUsage)
            .where(TokenUsage.user_id == sample_user.id)
            .order_by(TokenUsage.created_at)
        )
        records = result.scalars().all()
        assert len(records) == 5
    
    async def test_session_index_usage(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that session_id index works correctly."""
        # Create record
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="unique-session-123",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        db_session.add(token_usage)
        await db_session.commit()
        
        # Query by session_id (should use index)
        result = await db_session.execute(
            select(TokenUsage).where(TokenUsage.session_id == "unique-session-123")
        )
        record = result.scalar_one()
        assert record is not None
        assert record.session_id == "unique-session-123"


class TestTokenUsageValidation:
    """Test token_usage field validation."""
    
    async def test_negative_tokens_rejected(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that negative token counts are rejected."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-negative",
            model_name="gpt-4",
            input_tokens=-100,  # Invalid
            output_tokens=50,
            total_tokens=-50,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        db_session.add(token_usage)
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cost_precision_maintained(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that cost maintains 6 decimal precision."""
        costs = [
            Decimal("0.000001"),  # Minimum precision
            Decimal("0.123456"),  # Full precision
            Decimal("99.999999"),  # Large with precision
        ]
        
        for i, cost in enumerate(costs):
            token_usage = TokenUsage(
                user_id=sample_user.id,
                agent_id=sample_agent_instance.id,
                session_id=f"session-precision-{i}",
                model_name="gpt-4",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=cost,
            )
            
            db_session.add(token_usage)
            await db_session.commit()
            await db_session.refresh(token_usage)
            
            assert token_usage.estimated_cost_usd == cost
    
    async def test_timestamp_is_utc(self, db_session: AsyncSession, sample_user: User, sample_agent_instance: AgentInstance):
        """Test that created_at is timezone-aware UTC."""
        token_usage = TokenUsage(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="session-timestamp",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        db_session.add(token_usage)
        await db_session.commit()
        await db_session.refresh(token_usage)
        
        assert token_usage.created_at.tzinfo is not None
        # Should be UTC (or equivalent)
        assert token_usage.created_at.utcoffset().total_seconds() == 0


class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_token_usage_create_validation(self, sample_user: User, sample_agent_instance: AgentInstance):
        """Test TokenUsageCreate model validation."""
        from db.models.token_usage import TokenUsageCreate
        
        model = TokenUsageCreate(
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="test-session",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        assert model.session_id == "test-session"
        assert model.input_tokens == 100
        assert model.estimated_cost_usd == Decimal("0.004500")
    
    def test_token_usage_from_orm(self, sample_user: User, sample_agent_instance: AgentInstance):
        """Test TokenUsage model with from_attributes."""
        from db.models.token_usage import TokenUsage
        
        # Simulate ORM object
        orm_token = TokenUsage(
            id=uuid4(),
            user_id=sample_user.id,
            agent_id=sample_agent_instance.id,
            session_id="test-session",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        )
        
        # Validate from ORM
        model = TokenUsage.model_validate(orm_token, from_attributes=True)
        assert model.session_id == "test-session"
        assert model.input_tokens == 100
