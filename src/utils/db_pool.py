"""Database connection pool module."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any, AsyncIterator, Optional, Type

import asyncpg

from i18n import _

logger = logging.getLogger(__name__)


# =============================================================================
# Global Pool Instance
# =============================================================================

# Global pool instance - initialized lazily or via configure_pool()
_pool: Optional[DatabasePool] = None
_pool_lock = asyncio.Lock()

async def configure_pool(config: Optional[PoolConfig] = None, dsn: Optional[str] = None) -> DatabasePool:
    """Configure the global database pool with custom settings.

    This function allows setting up the global pool with a custom DSN
    (primarily for testing). If the pool is already initialized, it will
    be closed and recreated with the new configuration.

    Args:
        config: Optional PoolConfig instance. If None, uses environment variables.
        dsn: Optional DSN string. If provided, creates a PoolConfig with this DSN.

    Returns:
        The configured global DatabasePool instance.

    Example:
        # For testing with a custom DSN
        await configure_pool(dsn="postgresql://user:pass@host:port/db")

        # For production (uses environment variables)
        await configure_pool()
    """
    global _pool

    async with _pool_lock:
        # Close existing pool if any
        if _pool is not None:
            try:
                await _pool.close()
            except Exception:
                pass
            _pool = None

        # Create new pool with provided config
        if dsn is not None:
            pool_config = PoolConfig(dsn=dsn)
        elif config is not None:
            pool_config = config
        else:
            pool_config = get_pool_config()

        _pool = DatabasePool(pool_config)
        await _pool.initialize()
        return _pool


async def get_pool() -> DatabasePool:
    """Get the global database pool instance.

    If the pool is not yet initialized, initializes it using environment
    variables.

    Returns:
        The global DatabasePool instance.
    """
    global _pool

    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = DatabasePool()
                await _pool.initialize()

    return _pool


async def close_pool() -> None:
    """Close the global database pool and release all resources.
    
    This function should be called at application shutdown or when
    cleaning up after tests to ensure all database connections are
    properly released.
    
    Thread-safe - uses the global pool lock to prevent race conditions.
    """
    global _pool
    
    async with _pool_lock:
        if _pool is not None:
            try:
                await _pool.close()
            except Exception:
                logger.exception(_("Error closing global database pool"))
            finally:
                _pool = None


@dataclass
class PoolConfig:
    """Configuration for database connection pool.

    Attributes:
        dsn: PostgreSQL connection string (Data Source Name)
        min_size: Minimum number of connections in the pool
        max_size: Maximum number of connections in the pool
        command_timeout: Default timeout for queries in seconds
        max_queries: Maximum queries per connection before reconnecting
        max_inactive_connection_lifetime: Seconds before closing idle connections
        timeout: Connection acquisition timeout in seconds
        server_settings: PostgreSQL session settings (e.g., search_path)
    """

    dsn: str
    min_size: int = 10
    max_size: int = 20
    command_timeout: int = 180
    max_queries: int = 50000
    max_inactive_connection_lifetime: int = 300
    timeout: int = 60
    server_settings: Optional[dict[str, str]] = None


def _validate_env_var(name: str) -> str:
    """Validate that an environment variable is set.

    Args:
        name: Name of the environment variable

    Returns:
        The value of the environment variable

    Raises:
        RuntimeError: If the environment variable is not set
    """
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


def _build_dsn() -> str:
    """Build PostgreSQL DSN from environment variables.

    Constructs a DSN string from POSTGRES_HOST, POSTGRES_PORT,
    POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB environment
    variables.

    Returns:
        PostgreSQL DSN string in format:
        postgresql://user:password@host:port/database

    Raises:
        RuntimeError: If any required environment variable is missing
    """
    host = _validate_env_var("POSTGRES_HOST")
    port = _validate_env_var("POSTGRES_PORT")
    user = _validate_env_var("POSTGRES_USER")
    password = _validate_env_var("POSTGRES_PASSWORD")
    database = _validate_env_var("POSTGRES_DB")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def get_pool_config() -> PoolConfig:
    """Create pool configuration from environment variables.

    Returns:
        PoolConfig instance with DSN built from environment variables
        and pool settings from environment or defaults

    Raises:
        RuntimeError: If any required POSTGRES_* environment variable is missing
    """
    dsn = _build_dsn()

    min_size = int(os.getenv("POOL_MIN_SIZE", "10"))
    max_size = int(os.getenv("POOL_MAX_SIZE", "20"))

    return PoolConfig(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        server_settings={"search_path": "langgraph,public"},
    )


class DatabasePool:
    """Async PostgreSQL connection pool manager.

    Provides thread-safe initialization and connection management for asyncpg.
    """

    def __init__(self, config: Optional[PoolConfig] = None) -> None:
        """Initialize database pool manager.

        Args:
            config: Pool configuration. If None, reads from environment.
        """
        self._config = config or get_pool_config()
        self._pool: Optional[asyncpg.Pool] = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Create the asyncpg connection pool.

        Thread-safe - uses asyncio.Lock to prevent race conditions.

        Raises:
            RuntimeError: If pool initialization fails
        """
        async with self._lock:
            if self._initialized and self._pool is not None:
                return

            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self._config.dsn,
                    min_size=self._config.min_size,
                    max_size=self._config.max_size,
                    command_timeout=self._config.command_timeout,
                    max_queries=self._config.max_queries,
                    max_inactive_connection_lifetime=self._config.max_inactive_connection_lifetime,
                    timeout=self._config.timeout,
                    server_settings=self._config.server_settings,
                )
                self._initialized = True
            except Exception as e:
                self._pool = None
                self._initialized = False
                raise RuntimeError(f"Failed to initialize database pool: {e}") from e

    async def close(self) -> None:
        """Close the connection pool and release all resources.

        Thread-safe - uses asyncio.Lock to prevent race conditions.
        """
        async with self._lock:
            if self._pool is not None:
                await self._pool.close()
                self._pool = None
            self._initialized = False

    async def _reconnect(self) -> None:
        """Recreate the connection pool on connection failure.

        Uses exponential backoff with a maximum of 5 retry attempts.
        Handles InterfaceError and connection-related asyncpg exceptions gracefully.

        Raises:
            ConnectionError: If reconnection fails after maximum retries.
        """
        max_attempts = 5
        base_delay = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                if self._pool is not None:
                    try:
                        await self._pool.close()
                    except Exception:
                        pass  # Ignore errors when closing broken pool
                    self._pool = None

                self._pool = await asyncpg.create_pool(
                    dsn=self._config.dsn,
                    min_size=self._config.min_size,
                    max_size=self._config.max_size,
                    command_timeout=self._config.command_timeout,
                    max_queries=self._config.max_queries,
                    max_inactive_connection_lifetime=self._config.max_inactive_connection_lifetime,
                    timeout=self._config.timeout,
                    server_settings=self._config.server_settings,
                )
                self._initialized = True
                logger.warning(
                    "Database pool reconnection successful on attempt %d/%d",
                    attempt,
                    max_attempts,
                )
                return

            except (
                asyncpg.InterfaceError,
                asyncpg.ConnectionDoesNotExistError,
                asyncpg.ConnectionFailureError,
                OSError,
            ) as e:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Database pool reconnection attempt %d/%d failed: %s. "
                    "Retrying in %.1f seconds...",
                    attempt,
                    max_attempts,
                    str(e),
                    delay,
                )

                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                else:
                    self._initialized = False
                    self._pool = None
                    raise ConnectionError(
                        f"Failed to reconnect to database after {max_attempts} attempts: {e}"
                    ) from e

            except Exception as e:
                self._initialized = False
                self._pool = None
                raise ConnectionError(
                    f"Unexpected error during database reconnection: {e}"
                ) from e

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call initialize() first.")

        async with self._pool.acquire() as connection:
            yield connection

    @property
    def is_initialized(self) -> bool:
        """Check if pool is initialized."""
        return self._initialized and self._pool is not None

    async def __aenter__(self) -> "DatabasePool":
        """Async context manager entry - initializes pool."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        """Async context manager exit - closes pool."""
        await self.close()

    async def health_check(self, timeout: int = 5) -> bool:
        """Check if the database pool is healthy.

        Executes a simple SELECT 1 query to verify connectivity.

        Args:
            timeout: Query timeout in seconds (default: 5)

        Returns:
            True if pool is healthy and responsive, False on any failure
        """
        if self._pool is None:
            return False

        try:
            async with self._pool.acquire() as connection:
                await asyncio.wait_for(
                    connection.execute("SELECT 1"),
                    timeout=timeout,
                )
            return True
        except (asyncpg.PostgresError, asyncio.TimeoutError, Exception):
            return False

    def get_size(self) -> int:
        """Get current pool size.

        Returns:
            Current number of connections in the pool
        """
        if self._pool is None:
            return 0
        return self._pool.get_size()

    def get_idle_size(self) -> int:
        """Get number of idle connections in the pool.

        Returns:
            Number of idle connections available
        """
        if self._pool is None:
            return 0
        return self._pool.get_idle_size()

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics.

        Returns:
            Dictionary with keys: size, idle, used, max_size, min_size
        """
        size = self.get_size()
        idle = self.get_idle_size()

        return {
            "size": size,
            "idle": idle,
            "used": size - idle,
            "max_size": self._config.max_size,
            "min_size": self._config.min_size,
        }
