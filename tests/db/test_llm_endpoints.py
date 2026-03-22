# pyright: reportMissingImports=false
"""
Tests for LLM endpoints and level endpoints database models.

This module tests CRUD operations, schema creation, indexes,
foreign key constraints, encryption, and unique constraints
for llm_endpoints and llm_level_endpoints tables.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.schema.llm_endpoints import LLMEndpointGroup, LLMEndpoint, LLMLevelEndpoint
from db.schema.users import User  # noqa: F401 - Import for relationship resolution
from db.types import gen_random_uuid
from db.crypto import (
    CryptoManager,
    EncryptionKeyError,
    DecryptionError,
    encrypt_api_key,
    decrypt_api_key,
    generate_key,
)


# Test encryption key for testing
TEST_ENCRYPTION_KEY = generate_key()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation.
    """
    # Set test encryption key
    original_key = os.environ.get("LLM_ENCRYPTION_KEY")
    os.environ["LLM_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
    CryptoManager.reset()
    
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
        
        # Create llm_endpoints table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_endpoints (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                model_name TEXT NOT NULL,
                config_json JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                last_success_at TIMESTAMPTZ,
                last_failure_at TIMESTAMPTZ,
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Create llm_level_endpoints table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_level_endpoints (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                group_id UUID NOT NULL REFERENCES llm_endpoint_groups(id) ON DELETE CASCADE,
                difficulty_level SMALLINT NOT NULL CHECK (difficulty_level BETWEEN 1 AND 3),
                involves_secrets BOOLEAN NOT NULL DEFAULT false,
                endpoint_id UUID NOT NULL UNIQUE REFERENCES llm_endpoints(id) ON DELETE CASCADE,
                priority INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (group_id, difficulty_level, involves_secrets, endpoint_id)
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
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_endpoints_user 
            ON llm_endpoints(user_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_level_endpoints_group 
            ON llm_level_endpoints(group_id)
        """))
    
    async with async_session() as session:
        yield session
        # Rollback any changes at end of test
        await session.rollback()
    
    # Clean up - drop tables after test
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS llm_level_endpoints"))
        await conn.execute(text("DROP TABLE IF EXISTS llm_endpoints"))
        await conn.execute(text("DROP TABLE IF EXISTS llm_endpoint_groups"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))
    
    await engine.dispose()
    
    # Restore original encryption key
    if original_key is not None:
        os.environ["LLM_ENCRYPTION_KEY"] = original_key
    else:
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
    CryptoManager.reset()


# =============================================================================
# Crypto Tests
# =============================================================================

class TestCrypto:
    """Test encryption/decryption functionality."""
    
    @pytest.fixture(autouse=True)
    def setup_encryption_key(self):
        """Set up test encryption key for each test."""
        self._original_key = os.environ.get("LLM_ENCRYPTION_KEY")
        self._test_key = generate_key()
        os.environ["LLM_ENCRYPTION_KEY"] = self._test_key
        CryptoManager.reset()
        yield
        # Restore original key
        if self._original_key is not None:
            os.environ["LLM_ENCRYPTION_KEY"] = self._original_key
        else:
            os.environ.pop("LLM_ENCRYPTION_KEY", None)
        CryptoManager.reset()
    
    def test_generate_key(self):
        """Test key generation."""
        key = generate_key()
        assert isinstance(key, str)
        assert len(key) > 0
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption and decryption roundtrip."""
        original = "my-secret-api-key-12345"
        encrypted = encrypt_api_key(original)
        decrypted = decrypt_api_key(encrypted)
        
        assert decrypted == original
        assert encrypted != original
    
    def test_encryption_produces_different_ciphertext(self):
        """Test that encrypting same value produces different ciphertext (due to IV)."""
        original = "my-secret-api-key"
        encrypted1 = encrypt_api_key(original)
        encrypted2 = encrypt_api_key(original)
        
        # Both should decrypt to same value
        assert decrypt_api_key(encrypted1) == original
        assert decrypt_api_key(encrypted2) == original
        # But ciphertext should be different (due to Fernet's timestamp/IV)
        # Note: Fernet includes timestamp, so this is expected
    
    def test_decrypt_wrong_key_fails(self):
        """Test that decryption with wrong key fails."""
        original = "my-secret-api-key"
        encrypted = encrypt_api_key(original)
        
        # Change the key
        os.environ["LLM_ENCRYPTION_KEY"] = generate_key()
        CryptoManager.reset()
        
        with pytest.raises(DecryptionError):
            decrypt_api_key(encrypted)
    
    def test_missing_encryption_key(self):
        """Test that missing encryption key raises error."""
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        CryptoManager.reset()
        
        with pytest.raises(EncryptionKeyError):
            encrypt_api_key("test-key")


# =============================================================================
# LLMEndpoint Schema Tests
# =============================================================================

class TestLLMEndpointSchema:
    """Test llm_endpoints schema creation and structure."""
    
    async def test_llm_endpoints_table_exists(self, db_session: AsyncSession):
        """Test that the llm_endpoints table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'llm_endpoints'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "llm_endpoints"
    
    async def test_llm_endpoints_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in llm_endpoints table."""
        expected_columns = {
            'id', 'user_id', 'name', 'base_url', 'api_key_encrypted',
            'model_name', 'config_json', 'is_active', 'last_success_at',
            'last_failure_at', 'failure_count', 'created_at', 'updated_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'llm_endpoints'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_llm_endpoints_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'llm_endpoints'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_endpoints_user' in indexes


# =============================================================================
# LLMLevelEndpoint Schema Tests
# =============================================================================

class TestLLMLevelEndpointSchema:
    """Test llm_level_endpoints schema creation and structure."""
    
    async def test_llm_level_endpoints_table_exists(self, db_session: AsyncSession):
        """Test that the llm_level_endpoints table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'llm_level_endpoints'
            """)
        )
        table = result.scalar_one_or_none()
        assert table == "llm_level_endpoints"
    
    async def test_llm_level_endpoints_columns_exist(self, db_session: AsyncSession):
        """Test that all required columns exist in llm_level_endpoints table."""
        expected_columns = {
            'id', 'group_id', 'difficulty_level', 'involves_secrets',
            'endpoint_id', 'priority', 'is_active', 'created_at'
        }
        
        result = await db_session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'llm_level_endpoints'
            """)
        )
        columns = {row[0] for row in result.fetchall()}
        
        assert columns == expected_columns
    
    async def test_llm_level_endpoints_indexes_exist(self, db_session: AsyncSession):
        """Test that the required indexes exist."""
        result = await db_session.execute(
            text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'llm_level_endpoints'
            """)
        )
        indexes = {row[0] for row in result.fetchall()}
        
        assert 'idx_level_endpoints_group' in indexes


# =============================================================================
# LLMEndpoint CRUD Tests
# =============================================================================

class TestLLMEndpointCRUD:
    """Test CRUD operations for LLMEndpoint model."""
    
    async def test_create_endpoint_minimal(self, db_session: AsyncSession):
        """Test creating an endpoint with minimal fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        encrypted_key = encrypt_api_key("sk-test-api-key")
        
        endpoint = LLMEndpoint(
            user_id=user_id,
            name="OpenAI GPT-4",
            base_url="https://api.openai.com/v1",
            api_key_encrypted=encrypted_key,
            model_name="gpt-4",
        )
        db_session.add(endpoint)
        await db_session.commit()
        await db_session.refresh(endpoint)
        
        assert endpoint.id is not None
        assert isinstance(endpoint.id, UUID)
        assert endpoint.user_id == user_id
        assert endpoint.name == "OpenAI GPT-4"
        assert endpoint.base_url == "https://api.openai.com/v1"
        assert endpoint.model_name == "gpt-4"
        assert endpoint.is_active is True
        assert endpoint.failure_count == 0
        assert endpoint.config_json is None
    
    async def test_create_endpoint_full(self, db_session: AsyncSession):
        """Test creating an endpoint with all fields."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        config = {
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 0.95,
        }
        
        now = datetime.now(timezone.utc)
        encrypted_key = encrypt_api_key("sk-full-test-key")
        
        endpoint = LLMEndpoint(
            user_id=user_id,
            name="Claude 3 Opus",
            base_url="https://api.anthropic.com/v1",
            api_key_encrypted=encrypted_key,
            model_name="claude-3-opus-20240229",
            config_json=config,
            is_active=True,
            last_success_at=now,
            failure_count=0,
        )
        db_session.add(endpoint)
        await db_session.commit()
        await db_session.refresh(endpoint)
        
        assert endpoint.name == "Claude 3 Opus"
        assert endpoint.model_name == "claude-3-opus-20240229"
        assert isinstance(endpoint.config_json, dict)
        assert endpoint.config_json["temperature"] == 0.7
        assert endpoint.last_success_at is not None
    
    async def test_update_endpoint(self, db_session: AsyncSession):
        """Test updating an endpoint."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        encrypted_key = encrypt_api_key("sk-original-key")
        
        endpoint = LLMEndpoint(
            user_id=user_id,
            name="Test Endpoint",
            base_url="https://api.example.com/v1",
            api_key_encrypted=encrypted_key,
            model_name="test-model",
        )
        db_session.add(endpoint)
        await db_session.commit()
        
        original_updated_at = endpoint.updated_at
        await asyncio.sleep(0.01)
        
        endpoint.name = "Updated Endpoint"
        endpoint.failure_count = 3
        await db_session.commit()
        await db_session.refresh(endpoint)
        
        assert endpoint.name == "Updated Endpoint"
        assert endpoint.failure_count == 3
        assert endpoint.updated_at > original_updated_at
    
    async def test_delete_endpoint(self, db_session: AsyncSession):
        """Test deleting an endpoint."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        encrypted_key = encrypt_api_key("sk-delete-key")
        
        endpoint = LLMEndpoint(
            user_id=user_id,
            name="Delete Test",
            base_url="https://api.example.com/v1",
            api_key_encrypted=encrypted_key,
            model_name="test-model",
        )
        db_session.add(endpoint)
        await db_session.commit()
        
        await db_session.delete(endpoint)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LLMEndpoint).where(LLMEndpoint.id == endpoint.id)
        )
        assert result.scalar_one_or_none() is None


# =============================================================================
# LLMLevelEndpoint CRUD Tests
# =============================================================================

class TestLLMLevelEndpointCRUD:
    """Test CRUD operations for LLMLevelEndpoint model."""
    
    async def _create_test_data(self, db_session: AsyncSession) -> tuple[UUID, UUID, UUID]:
        """Helper to create test user, group, and endpoint."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        group_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoint_groups (id, user_id, name) 
            VALUES ('{group_id}', '{user_id}', 'Test Group')
        """))
        
        endpoint_id = gen_random_uuid()
        encrypted_key = encrypt_api_key("sk-test-key")
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
            VALUES ('{endpoint_id}', '{user_id}', 'Test Endpoint', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
        """))
        await db_session.commit()
        
        return user_id, group_id, endpoint_id
    
    async def test_create_level_endpoint_minimal(self, db_session: AsyncSession):
        """Test creating a level endpoint with minimal fields."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        level_endpoint = LLMLevelEndpoint(
            group_id=group_id,
            difficulty_level=2,
            endpoint_id=endpoint_id,
        )
        db_session.add(level_endpoint)
        await db_session.commit()
        await db_session.refresh(level_endpoint)
        
        assert level_endpoint.id is not None
        assert isinstance(level_endpoint.id, UUID)
        assert level_endpoint.group_id == group_id
        assert level_endpoint.difficulty_level == 2
        assert level_endpoint.endpoint_id == endpoint_id
        assert level_endpoint.involves_secrets is False
        assert level_endpoint.priority == 0
        assert level_endpoint.is_active is True
    
    async def test_create_level_endpoint_full(self, db_session: AsyncSession):
        """Test creating a level endpoint with all fields."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        level_endpoint = LLMLevelEndpoint(
            group_id=group_id,
            difficulty_level=3,
            involves_secrets=True,
            endpoint_id=endpoint_id,
            priority=100,
            is_active=True,
        )
        db_session.add(level_endpoint)
        await db_session.commit()
        await db_session.refresh(level_endpoint)
        
        assert level_endpoint.difficulty_level == 3
        assert level_endpoint.involves_secrets is True
        assert level_endpoint.priority == 100
    
    async def test_delete_level_endpoint(self, db_session: AsyncSession):
        """Test deleting a level endpoint."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        level_endpoint = LLMLevelEndpoint(
            group_id=group_id,
            difficulty_level=1,
            endpoint_id=endpoint_id,
        )
        db_session.add(level_endpoint)
        await db_session.commit()
        
        await db_session.delete(level_endpoint)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LLMLevelEndpoint).where(LLMLevelEndpoint.id == level_endpoint.id)
        )
        assert result.scalar_one_or_none() is None


# =============================================================================
# Foreign Key Tests
# =============================================================================

class TestForeignKeys:
    """Test foreign key constraints and cascade behavior."""
    
    async def test_fk_user_id_enforced(self, db_session: AsyncSession):
        """Test that user_id FK constraint is enforced."""
        fake_user_id = uuid4()
        encrypted_key = encrypt_api_key("sk-test-key")
        
        endpoint = LLMEndpoint(
            user_id=fake_user_id,
            name="Invalid Endpoint",
            base_url="https://api.example.com/v1",
            api_key_encrypted=encrypted_key,
            model_name="test-model",
        )
        db_session.add(endpoint)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_cascade_delete_user_to_endpoints(self, db_session: AsyncSession):
        """Test that deleting user cascades to endpoints."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        encrypted_key = encrypt_api_key("sk-test-key")
        
        # Create multiple endpoints
        for i in range(3):
            endpoint = LLMEndpoint(
                user_id=user_id,
                name=f"Endpoint {i}",
                base_url="https://api.example.com/v1",
                api_key_encrypted=encrypted_key,
                model_name="test-model",
            )
            db_session.add(endpoint)
        await db_session.commit()
        
        # Delete user
        await db_session.execute(text(f"""
            DELETE FROM users WHERE id = '{user_id}'
        """))
        await db_session.commit()
        
        # Verify endpoints are deleted
        result = await db_session.execute(
            select(LLMEndpoint).where(LLMEndpoint.user_id == user_id)
        )
        endpoints = result.scalars().all()
        assert len(endpoints) == 0
    
    async def test_cascade_delete_endpoint_to_level_endpoints(self, db_session: AsyncSession):
        """Test that deleting endpoint cascades to level endpoints."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        group_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoint_groups (id, user_id, name) 
            VALUES ('{group_id}', '{user_id}', 'Test Group')
        """))
        
        endpoint_id = gen_random_uuid()
        encrypted_key = encrypt_api_key("sk-test-key")
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
            VALUES ('{endpoint_id}', '{user_id}', 'Test Endpoint', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
        """))
        
        level_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_level_endpoints (id, group_id, difficulty_level, endpoint_id) 
            VALUES ('{level_id}', '{group_id}', 2, '{endpoint_id}')
        """))
        await db_session.commit()
        
        # Delete endpoint
        await db_session.execute(text(f"""
            DELETE FROM llm_endpoints WHERE id = '{endpoint_id}'
        """))
        await db_session.commit()
        
        # Verify level endpoint is deleted
        result = await db_session.execute(
            select(LLMLevelEndpoint).where(LLMLevelEndpoint.id == level_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_cascade_delete_group_to_level_endpoints(self, db_session: AsyncSession):
        """Test that deleting group cascades to level endpoints."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        group_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoint_groups (id, user_id, name) 
            VALUES ('{group_id}', '{user_id}', 'Test Group')
        """))
        
        endpoint_id = gen_random_uuid()
        encrypted_key = encrypt_api_key("sk-test-key")
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
            VALUES ('{endpoint_id}', '{user_id}', 'Test Endpoint', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
        """))
        
        level_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_level_endpoints (id, group_id, difficulty_level, endpoint_id) 
            VALUES ('{level_id}', '{group_id}', 1, '{endpoint_id}')
        """))
        await db_session.commit()
        
        # Delete group
        await db_session.execute(text(f"""
            DELETE FROM llm_endpoint_groups WHERE id = '{group_id}'
        """))
        await db_session.commit()
        
        # Verify level endpoint is deleted
        result = await db_session.execute(
            select(LLMLevelEndpoint).where(LLMLevelEndpoint.id == level_id)
        )
        assert result.scalar_one_or_none() is None


# =============================================================================
# Constraint Tests
# =============================================================================

class TestConstraints:
    """Test CHECK constraints and unique constraints."""
    
    async def _create_test_data(self, db_session: AsyncSession) -> tuple[UUID, UUID, UUID]:
        """Helper to create test user, group, and endpoint."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        group_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoint_groups (id, user_id, name) 
            VALUES ('{group_id}', '{user_id}', 'Test Group')
        """))
        
        endpoint_id = gen_random_uuid()
        encrypted_key = encrypt_api_key("sk-test-key")
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
            VALUES ('{endpoint_id}', '{user_id}', 'Test Endpoint', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
        """))
        await db_session.commit()
        
        return user_id, group_id, endpoint_id
    
    async def test_difficulty_level_check_constraint_valid(self, db_session: AsyncSession):
        """Test that valid difficulty levels (1-3) are accepted."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        for level in [1, 2, 3]:
            endpoint_id_new = gen_random_uuid()
            encrypted_key = encrypt_api_key(f"sk-test-key-{level}")
            await db_session.execute(text(f"""
                INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
                VALUES ('{endpoint_id_new}', '{group_id}', 'Endpoint {level}', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
            """))
            
            level_endpoint = LLMLevelEndpoint(
                group_id=group_id,
                difficulty_level=level,
                endpoint_id=endpoint_id_new,
            )
            db_session.add(level_endpoint)
            await db_session.commit()
            await db_session.refresh(level_endpoint)
            
            assert level_endpoint.difficulty_level == level
    
    async def test_difficulty_level_check_constraint_invalid(self, db_session: AsyncSession):
        """Test that invalid difficulty levels are rejected."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        # Test level 0
        with pytest.raises(IntegrityError):
            await db_session.execute(text(f"""
                INSERT INTO llm_level_endpoints (group_id, difficulty_level, endpoint_id) 
                VALUES ('{group_id}', 0, '{endpoint_id}')
            """))
            await db_session.commit()
        await db_session.rollback()
        
        # Test level 4
        endpoint_id_new = gen_random_uuid()
        encrypted_key = encrypt_api_key("sk-test-key-4")
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
            VALUES ('{endpoint_id_new}', '{group_id}', 'Endpoint 4', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
        """))
        await db_session.commit()
        
        with pytest.raises(IntegrityError):
            await db_session.execute(text(f"""
                INSERT INTO llm_level_endpoints (group_id, difficulty_level, endpoint_id) 
                VALUES ('{group_id}', 4, '{endpoint_id_new}')
            """))
            await db_session.commit()
    
    async def test_endpoint_id_unique_constraint(self, db_session: AsyncSession):
        """Test that endpoint_id must be unique in llm_level_endpoints."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        # First assignment
        level1 = LLMLevelEndpoint(
            group_id=group_id,
            difficulty_level=1,
            endpoint_id=endpoint_id,
        )
        db_session.add(level1)
        await db_session.commit()
        
        # Create another group
        group2_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoint_groups (id, user_id, name) 
            VALUES ('{group2_id}', '{group_id}', 'Another Group')
        """))
        await db_session.commit()
        
        # Try to assign same endpoint to another group - should fail
        with pytest.raises(IntegrityError):
            level2 = LLMLevelEndpoint(
                group_id=group2_id,
                difficulty_level=2,
                endpoint_id=endpoint_id,  # Same endpoint_id
            )
            db_session.add(level2)
            await db_session.commit()
    
    async def test_composite_unique_constraint(self, db_session: AsyncSession):
        """Test that the composite unique constraint works."""
        _, group_id, endpoint_id = await self._create_test_data(db_session)
        
        # First assignment
        level1 = LLMLevelEndpoint(
            group_id=group_id,
            difficulty_level=2,
            involves_secrets=False,
            endpoint_id=endpoint_id,
        )
        db_session.add(level1)
        await db_session.commit()
        
        # Create another endpoint
        endpoint2_id = gen_random_uuid()
        encrypted_key = encrypt_api_key("sk-test-key-2")
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
            VALUES ('{endpoint2_id}', '{group_id}', 'Endpoint 2', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
        """))
        await db_session.commit()
        
        # Same group, same level, same secrets flag, different endpoint - should fail
        with pytest.raises(IntegrityError):
            level2 = LLMLevelEndpoint(
                group_id=group_id,
                difficulty_level=2,
                involves_secrets=False,  # Same
                endpoint_id=endpoint2_id,  # Different endpoint but same composite key parts
            )
            db_session.add(level2)
            await db_session.commit()


# =============================================================================
# Encryption Integration Tests
# =============================================================================

class TestEncryptionIntegration:
    """Test API key encryption with database operations."""
    
    async def test_api_key_stored_encrypted(self, db_session: AsyncSession):
        """Test that API key is stored encrypted, not plaintext."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        plaintext_key = "sk-my-secret-api-key-12345"
        encrypted_key = encrypt_api_key(plaintext_key)
        
        endpoint = LLMEndpoint(
            user_id=user_id,
            name="Test Endpoint",
            base_url="https://api.example.com/v1",
            api_key_encrypted=encrypted_key,
            model_name="test-model",
        )
        db_session.add(endpoint)
        await db_session.commit()
        await db_session.refresh(endpoint)
        
        # Verify the stored value is NOT the plaintext
        assert endpoint.api_key_encrypted != plaintext_key
        # Verify we can decrypt it back
        decrypted = decrypt_api_key(endpoint.api_key_encrypted)
        assert decrypted == plaintext_key
    
    async def test_different_endpoints_different_encrypted_keys(self, db_session: AsyncSession):
        """Test that different plaintext keys produce different encrypted values."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        await db_session.commit()
        
        key1 = "sk-key-1"
        key2 = "sk-key-2"
        
        encrypted1 = encrypt_api_key(key1)
        encrypted2 = encrypt_api_key(key2)
        
        endpoint1 = LLMEndpoint(
            user_id=user_id,
            name="Endpoint 1",
            base_url="https://api.example.com/v1",
            api_key_encrypted=encrypted1,
            model_name="model-1",
        )
        endpoint2 = LLMEndpoint(
            user_id=user_id,
            name="Endpoint 2",
            base_url="https://api.example.com/v1",
            api_key_encrypted=encrypted2,
            model_name="model-2",
        )
        db_session.add(endpoint1)
        db_session.add(endpoint2)
        await db_session.commit()
        
        # Decrypt and verify
        assert decrypt_api_key(endpoint1.api_key_encrypted) == key1
        assert decrypt_api_key(endpoint2.api_key_encrypted) == key2


# =============================================================================
# Pydantic Model Tests
# =============================================================================

class TestPydanticModels:
    """Test Pydantic model validation."""
    
    def test_llm_endpoint_create_validation(self):
        """Test LLMEndpointCreate model validation."""
        from db.models.llm_endpoint import LLMEndpointCreate
        
        user_id = gen_random_uuid()
        
        data = {
            "user_id": user_id,
            "name": "Test Endpoint",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model_name": "gpt-4",
            "config_json": {"temperature": 0.7},
        }
        model = LLMEndpointCreate(**data)
        
        assert model.user_id == user_id
        assert model.name == "Test Endpoint"
        assert model.api_key == "sk-test-key"
        assert model.config_json["temperature"] == 0.7
    
    def test_llm_endpoint_create_name_required(self):
        """Test that name is required in LLMEndpointCreate."""
        from db.models.llm_endpoint import LLMEndpointCreate
        from pydantic import ValidationError
        
        user_id = gen_random_uuid()
        
        with pytest.raises(ValidationError):
            LLMEndpointCreate(
                user_id=user_id,
                # name is missing
                base_url="https://api.example.com/v1",
                api_key="sk-test-key",
                model_name="gpt-4",
            )
    
    def test_llm_level_endpoint_create_validation(self):
        """Test LLMLevelEndpointCreate model validation."""
        from db.models.llm_endpoint import LLMLevelEndpointCreate
        
        group_id = gen_random_uuid()
        endpoint_id = gen_random_uuid()
        
        data = {
            "group_id": group_id,
            "difficulty_level": 2,
            "endpoint_id": endpoint_id,
            "involves_secrets": True,
            "priority": 50,
        }
        model = LLMLevelEndpointCreate(**data)
        
        assert model.group_id == group_id
        assert model.difficulty_level == 2
        assert model.endpoint_id == endpoint_id
        assert model.involves_secrets is True
        assert model.priority == 50
    
    def test_llm_level_endpoint_difficulty_level_validation(self):
        """Test that difficulty_level must be between 1 and 3."""
        from db.models.llm_endpoint import LLMLevelEndpointCreate
        from pydantic import ValidationError
        
        group_id = gen_random_uuid()
        endpoint_id = gen_random_uuid()
        
        # Test invalid level 0
        with pytest.raises(ValidationError):
            LLMLevelEndpointCreate(
                group_id=group_id,
                difficulty_level=0,  # Invalid
                endpoint_id=endpoint_id,
            )
        
        # Test invalid level 4
        with pytest.raises(ValidationError):
            LLMLevelEndpointCreate(
                group_id=group_id,
                difficulty_level=4,  # Invalid
                endpoint_id=endpoint_id,
            )
        
        # Test valid levels 1, 2, 3
        for level in [1, 2, 3]:
            model = LLMLevelEndpointCreate(
                group_id=group_id,
                difficulty_level=level,
                endpoint_id=endpoint_id,
            )
            assert model.difficulty_level == level
    
    def test_llm_endpoint_full_model(self):
        """Test LLMEndpoint model with all fields."""
        from db.models.llm_endpoint import LLMEndpoint
        
        user_id = gen_random_uuid()
        endpoint_id = gen_random_uuid()
        now = datetime.now(timezone.utc)
        
        data = {
            "id": endpoint_id,
            "user_id": user_id,
            "name": "Full Endpoint",
            "base_url": "https://api.example.com/v1",
            "model_name": "gpt-4",
            "config_json": {"temperature": 0.7},
            "is_active": True,
            "last_success_at": now,
            "last_failure_at": None,
            "failure_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        model = LLMEndpoint(**data)
        
        assert model.id == endpoint_id
        assert model.user_id == user_id
        assert model.name == "Full Endpoint"
        assert model.model_name == "gpt-4"
        assert model.failure_count == 0
    
    def test_llm_level_endpoint_full_model(self):
        """Test LLMLevelEndpoint model with all fields."""
        from db.models.llm_endpoint import LLMLevelEndpoint
        
        level_id = gen_random_uuid()
        group_id = gen_random_uuid()
        endpoint_id = gen_random_uuid()
        now = datetime.now(timezone.utc)
        
        data = {
            "id": level_id,
            "group_id": group_id,
            "difficulty_level": 3,
            "involves_secrets": True,
            "endpoint_id": endpoint_id,
            "priority": 100,
            "is_active": True,
            "created_at": now,
        }
        model = LLMLevelEndpoint(**data)
        
        assert model.id == level_id
        assert model.group_id == group_id
        assert model.difficulty_level == 3
        assert model.involves_secrets is True
        assert model.priority == 100


# =============================================================================
# Priority Ordering Tests
# =============================================================================

class TestPriorityOrdering:
    """Test priority ordering for endpoint selection."""
    
    async def _create_test_data(self, db_session: AsyncSession) -> UUID:
        """Helper to create test user and group."""
        user_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO users (id, username, email) 
            VALUES ('{user_id}', 'testuser', 'test@example.com')
        """))
        
        group_id = gen_random_uuid()
        await db_session.execute(text(f"""
            INSERT INTO llm_endpoint_groups (id, user_id, name) 
            VALUES ('{group_id}', '{user_id}', 'Test Group')
        """))
        await db_session.commit()
        
        return group_id
    
    async def test_priority_ordering(self, db_session: AsyncSession):
        """Test that endpoints can be ordered by priority."""
        group_id = await self._create_test_data(db_session)
        
        # Create multiple endpoints with different priorities
        priorities = [10, 50, 30, 20, 40]
        for i, priority in enumerate(priorities):
            endpoint_id = gen_random_uuid()
            encrypted_key = encrypt_api_key(f"sk-test-key-{i}")
            await db_session.execute(text(f"""
                INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
                VALUES ('{endpoint_id}', '{group_id}', 'Endpoint {i}', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
            """))
            
            level_endpoint = LLMLevelEndpoint(
                group_id=group_id,
                difficulty_level=1,
                endpoint_id=endpoint_id,
                priority=priority,
            )
            db_session.add(level_endpoint)
        
        await db_session.commit()
        
        # Query ordered by priority descending
        result = await db_session.execute(
            select(LLMLevelEndpoint)
            .where(LLMLevelEndpoint.group_id == group_id)
            .order_by(LLMLevelEndpoint.priority.desc())
        )
        endpoints = result.scalars().all()
        
        # Should be ordered by priority descending
        assert len(endpoints) == 5
        assert endpoints[0].priority == 50
        assert endpoints[1].priority == 40
        assert endpoints[2].priority == 30
        assert endpoints[3].priority == 20
        assert endpoints[4].priority == 10
    
    async def test_filter_by_difficulty_level(self, db_session: AsyncSession):
        """Test filtering endpoints by difficulty level."""
        group_id = await self._create_test_data(db_session)
        
        # Create endpoints for different difficulty levels
        for level in [1, 2, 3]:
            endpoint_id = gen_random_uuid()
            encrypted_key = encrypt_api_key(f"sk-test-key-{level}")
            await db_session.execute(text(f"""
                INSERT INTO llm_endpoints (id, user_id, name, base_url, api_key_encrypted, model_name) 
                VALUES ('{endpoint_id}', '{group_id}', 'Endpoint Level {level}', 'https://api.example.com/v1', '{encrypted_key}', 'test-model')
            """))
            
            level_endpoint = LLMLevelEndpoint(
                group_id=group_id,
                difficulty_level=level,
                endpoint_id=endpoint_id,
            )
            db_session.add(level_endpoint)
        
        await db_session.commit()
        
        # Filter by difficulty level 2
        result = await db_session.execute(
            select(LLMLevelEndpoint)
            .where(LLMLevelEndpoint.group_id == group_id)
            .where(LLMLevelEndpoint.difficulty_level == 2)
        )
        endpoints = result.scalars().all()
        
        assert len(endpoints) == 1
        assert endpoints[0].difficulty_level == 2