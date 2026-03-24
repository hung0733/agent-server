"""Database configuration and engine utilities.

This module provides database engine configuration compatible with
the existing async patterns from src/tools/db_pool.py.
"""

from __future__ import annotations

import os
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
    AsyncSession,
)
from sqlalchemy.pool import NullPool

from .base import Base


__all__ = [
    "Base",
    "create_engine",
    "get_dsn",
    "AsyncSession",
    "async_sessionmaker",
]


def get_dsn() -> str:
    """Build PostgreSQL DSN from environment variables.
    
    Matches the pattern from src/tools/db_pool.py for consistency.
    
    Returns:
        PostgreSQL DSN string in format:
        postgresql://user:password@host:port/database
        
    Raises:
        RuntimeError: If any required environment variable is missing
    """
    def _validate_env_var(name: str) -> str:
        value = os.getenv(name)
        if value is None:
            raise RuntimeError(f"Required environment variable '{name}' is not set")
        return value
    
    host = _validate_env_var("POSTGRES_HOST")
    port = _validate_env_var("POSTGRES_PORT")
    user = _validate_env_var("POSTGRES_USER")
    password = _validate_env_var("POSTGRES_PASSWORD")
    database = _validate_env_var("POSTGRES_DB")
    
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def create_engine(
    dsn: Optional[str] = None,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    echo: bool = False,
    poolclass: Optional[type] = None,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine for PostgreSQL.
    
    Args:
        dsn: Database connection string. If None, builds from environment variables.
        min_size: Minimum pool size (passed to asyncpg via connect_args).
        max_size: Maximum pool size (passed to asyncpg via connect_args).
        echo: If True, enable SQL query logging.
        poolclass: SQLAlchemy pool class to use. Defaults to NullPool.
        
    Returns:
        AsyncEngine instance configured for async operations with asyncpg.
        
    Example:
        engine = create_engine()
        
        # With custom DSN (for testing)
        engine = create_engine(dsn="postgresql+asyncpg://...")
        
        # With pool settings
        engine = create_engine(min_size=5, max_size=10)
    """
    if dsn is None:
        dsn = get_dsn()
    
    # Build connection arguments for asyncpg
    connect_args: dict = {}
    
    # Add pool settings if provided
    if min_size is not None:
        connect_args["min_size"] = min_size
    if max_size is not None:
        connect_args["max_size"] = max_size
    
    # App tables live in public schema only
    connect_args["server_settings"] = {"search_path": "public"}
    
    return create_async_engine(
        dsn,
        echo=echo,
        poolclass=poolclass or NullPool,
        connect_args=connect_args,
    )


# Convenience exports for common patterns
__all__.extend(["get_dsn", "create_engine"])
