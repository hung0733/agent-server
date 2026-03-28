"""Shared pytest fixtures for db_pool tests."""

from __future__ import annotations

import os
from typing import AsyncGenerator
from unittest.mock import MagicMock

import asyncpg

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession as SQLAAsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Ensure src imports resolve
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from utils.db_pool import DatabasePool, PoolConfig, close_pool
from tests.schema_config import (
    TEST_AUDIT_SCHEMA,
    TEST_LANGGRAPH_SCHEMA,
    TEST_PUBLIC_SCHEMA,
    TEST_SIMPLEME_SCHEMA,
    rewrite_sql_schemas,
)


_SCHEMA_REWRITE_HOOK_INSTALLED = False
_ASYNC_PG_PATCHED = False


def _install_sqlalchemy_schema_rewrite_hook() -> None:
    """Rewrite SQLAlchemy SQL from prod schemas to test schemas."""
    global _SCHEMA_REWRITE_HOOK_INSTALLED

    if _SCHEMA_REWRITE_HOOK_INSTALLED:
        return

    @event.listens_for(Engine, "before_cursor_execute", retval=True)
    def _rewrite_schemas_before_execute(  # type: ignore[unused-ignore]
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        if isinstance(statement, str):
            statement = rewrite_sql_schemas(statement)
        return statement, parameters

    _SCHEMA_REWRITE_HOOK_INSTALLED = True


def _patch_asyncpg_schema_rewrite() -> None:
    """Patch asyncpg APIs used in tests so raw SQL also targets test schemas."""
    global _ASYNC_PG_PATCHED

    if _ASYNC_PG_PATCHED:
        return

    def _wrap(name: str) -> None:
        original = getattr(asyncpg.connection.Connection, name)

        async def _patched(self, query, *args, **kwargs):
            if isinstance(query, str):
                query = rewrite_sql_schemas(query)
            return await original(self, query, *args, **kwargs)

        setattr(asyncpg.connection.Connection, f"_original_{name}", original)
        setattr(asyncpg.connection.Connection, name, _patched)

    _wrap("execute")
    _wrap("fetch")
    _wrap("fetchrow")
    _wrap("fetchval")

    _ASYNC_PG_PATCHED = True


async def _create_schema_if_missing(session: SQLAAsyncSession, schema: str) -> None:
    await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))


async def _clone_tables_to_test_schema(
    session: SQLAAsyncSession,
    source_schema: str,
    target_schema: str,
) -> None:
    result = await session.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :source_schema
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ),
        {"source_schema": source_schema},
    )

    table_names = [row[0] for row in result.fetchall()]
    for table_name in table_names:
        await session.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {target_schema}.\"{table_name}\"
                (LIKE {source_schema}.\"{table_name}\"
                    INCLUDING DEFAULTS
                    INCLUDING CONSTRAINTS
                    INCLUDING INDEXES
                    INCLUDING GENERATED
                    INCLUDING IDENTITY)
                """
            )
        )


@pytest.fixture(scope="session", autouse=True)
async def enforce_test_schemas() -> AsyncGenerator[None, None]:
    """Global test-safety fixture: force all test SQL to test_* schemas."""
    dsn = os.getenv("TEST_POSTGRES_DSN") or os.getenv("POSTGRES_DSN")
    if dsn is None:
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")
        host = os.getenv("POSTGRES_HOST")
        port = os.getenv("POSTGRES_PORT")
        db = os.getenv("POSTGRES_DB")

        required = {
            "POSTGRES_USER": user,
            "POSTGRES_PASSWORD": password,
            "POSTGRES_HOST": host,
            "POSTGRES_PORT": port,
            "POSTGRES_DB": db,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            # Allow pure unit tests to run without DB env.
            yield
            return

        dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

    engine = create_async_engine(dsn)
    async_session = async_sessionmaker(
        engine,
        class_=SQLAAsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        await _create_schema_if_missing(session, TEST_PUBLIC_SCHEMA)
        await _create_schema_if_missing(session, TEST_LANGGRAPH_SCHEMA)
        await _create_schema_if_missing(session, TEST_AUDIT_SCHEMA)
        await _create_schema_if_missing(session, TEST_SIMPLEME_SCHEMA)

        await _clone_tables_to_test_schema(session, "public", TEST_PUBLIC_SCHEMA)
        await _clone_tables_to_test_schema(session, "langgraph", TEST_LANGGRAPH_SCHEMA)
        await _clone_tables_to_test_schema(session, "audit", TEST_AUDIT_SCHEMA)
        await _clone_tables_to_test_schema(session, "simpleme", TEST_SIMPLEME_SCHEMA)

        await session.commit()

    _install_sqlalchemy_schema_rewrite_hook()
    _patch_asyncpg_schema_rewrite()

    try:
        yield
    finally:
        await engine.dispose()


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
