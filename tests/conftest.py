"""Shared pytest fixtures for db_pool tests."""

from __future__ import annotations

import os
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

# Ensure src imports resolve
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.db_pool import DatabasePool, PoolConfig, close_pool


# =============================================================================
# Pytest-asyncio configuration
# =============================================================================

pytest_plugins = ("pytest_asyncio",)


# =============================================================================
# Database Pool Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def db_pool() -> AsyncGenerator[DatabasePool, None]:
    """
    Create a DatabasePool instance for testing.
    
    Uses a mock DSN to avoid requiring real database connections.
    Pool is automatically closed after test completion.
    """
    pool = DatabasePool(
        config=PoolConfig(
            dsn="postgresql://test:test@localhost:5432/testdb"
        )
    )
    try:
        yield pool
    finally:
        # Ensure pool is closed, but handle case where _pool might be a MagicMock
        if pool._pool is not None and not isinstance(pool._pool, MagicMock):
            await pool.close()
        elif pool._pool is None:
            await pool.close()


@pytest_asyncio.fixture(scope="function")
async def initialized_pool() -> AsyncGenerator[DatabasePool, None]:
    """
    Create an initialized DatabasePool instance for testing.
    
    Uses a mock DSN. Pool is initialized and automatically closed after test.
    Note: This will fail to connect to a real database, so use with mocking.
    """
    pool = DatabasePool(
        config=PoolConfig(
            dsn="postgresql://test:test@localhost:5432/testdb"
        )
    )
    try:
        await pool.initialize()
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def clean_env():
    """
    Fixture to clean environment variables before each test.
    
    Saves current env vars and restores them after test.
    """
    saved_vars = {
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER"),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB"),
    }
    
    # Remove all POSTGRES_* vars
    for key in list(os.environ.keys()):
        if key.startswith("POSTGRES_"):
            del os.environ[key]
    
    yield
    
    # Restore saved vars
    for key, value in saved_vars.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]
