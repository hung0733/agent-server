"""Unit tests for DatabasePool module."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from utils.db_pool import (
    DatabasePool,
    PoolConfig,
    _build_dsn,
    _validate_env_var,
    configure_pool,
    get_pool,
    get_pool_config,
    close_pool,
)


# =============================================================================
# Test _validate_env_var
# =============================================================================

class TestValidateEnvVar:
    """Tests for _validate_env_var function."""

    def test_returns_value_when_set(self, clean_env):
        """Should return the value when environment variable is set."""
        os.environ["TEST_VAR"] = "test_value"
        result = _validate_env_var("TEST_VAR")
        assert result == "test_value"

    def test_raises_runtime_error_when_missing(self, clean_env):
        """Should raise RuntimeError when environment variable is missing."""
        with pytest.raises(RuntimeError, match="Required environment variable 'MISSING_VAR' is not set"):
            _validate_env_var("MISSING_VAR")


# =============================================================================
# Test _build_dsn
# =============================================================================

class TestBuildDsn:
    """Tests for _build_dsn function."""

    def test_builds_dsn_correctly(self, clean_env):
        """Should build DSN correctly from environment variables."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        result = _build_dsn()
        assert result == "postgresql://testuser:testpass@localhost:5432/testdb"

    def test_raises_when_host_missing(self, clean_env):
        """Should raise RuntimeError when POSTGRES_HOST is missing."""
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
            _build_dsn()

    def test_raises_when_port_missing(self, clean_env):
        """Should raise RuntimeError when POSTGRES_PORT is missing."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        with pytest.raises(RuntimeError, match="POSTGRES_PORT"):
            _build_dsn()

    def test_raises_when_user_missing(self, clean_env):
        """Should raise RuntimeError when POSTGRES_USER is missing."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        with pytest.raises(RuntimeError, match="POSTGRES_USER"):
            _build_dsn()

    def test_raises_when_password_missing(self, clean_env):
        """Should raise RuntimeError when POSTGRES_PASSWORD is missing."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_DB"] = "testdb"
        
        with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
            _build_dsn()

    def test_raises_when_db_missing(self, clean_env):
        """Should raise RuntimeError when POSTGRES_DB is missing."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        
        with pytest.raises(RuntimeError, match="POSTGRES_DB"):
            _build_dsn()


# =============================================================================
# Test get_pool_config
# =============================================================================

class TestGetPoolConfig:
    """Tests for get_pool_config function."""

    def test_returns_config_with_defaults(self, clean_env):
        """Should return PoolConfig with default values when env vars not set for pool settings."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        config = get_pool_config()
        
        assert config.dsn == "postgresql://testuser:testpass@localhost:5432/testdb"
        assert config.min_size == 10
        assert config.max_size == 20
        assert config.server_settings == {"search_path": "langgraph,public"}

    def test_uses_custom_pool_settings_from_env(self, clean_env):
        """Should use custom POOL_MIN_SIZE and POOL_MAX_SIZE from environment."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        os.environ["POOL_MIN_SIZE"] = "5"
        os.environ["POOL_MAX_SIZE"] = "15"
        
        config = get_pool_config()
        
        assert config.min_size == 5
        assert config.max_size == 15

    def test_raises_when_required_env_missing(self, clean_env):
        """Should raise RuntimeError when required POSTGRES_* env vars are missing."""
        with pytest.raises(RuntimeError):
            get_pool_config()


# =============================================================================
# Test DatabasePool initialization
# =============================================================================

class TestDatabasePoolInit:
    """Tests for DatabasePool initialization."""

    def test_init_with_config(self):
        """Should initialize with provided config."""
        config = PoolConfig(dsn="postgresql://test:test@localhost:5432/testdb")
        pool = DatabasePool(config=config)
        
        assert pool._config == config
        assert pool._pool is None
        assert pool._initialized is False

    def test_init_without_config(self, clean_env):
        """Should initialize with environment variables when no config provided."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        pool = DatabasePool()
        
        assert pool._config is not None
        assert "postgresql://testuser:testpass@localhost:5432/testdb" == pool._config.dsn

    def test_init_raises_when_env_missing(self, clean_env):
        """Should raise RuntimeError when required env vars are missing and no config provided."""
        with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
            DatabasePool()


# =============================================================================
# Test DatabasePool.initialize()
# =============================================================================

class TestDatabasePoolInitialize:
    """Tests for DatabasePool.initialize() method."""

    @pytest.mark.asyncio
    async def test_initialize_success(self, db_pool):
        """Should successfully initialize the pool."""
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool = AsyncMock()
            mock_create.return_value = mock_pool
            
            await db_pool.initialize()
            
            assert db_pool._initialized is True
            assert db_pool._pool is mock_pool
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, db_pool):
        """Should not recreate pool if already initialized."""
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool = AsyncMock()
            mock_create.return_value = mock_pool
            
            await db_pool.initialize()
            await db_pool.initialize()  # Second call should be no-op
            
            assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_initialize_failure(self, db_pool):
        """Should raise RuntimeError when initialization fails."""
        with patch("asyncpg.create_pool", new_callable=AsyncMock, side_effect=Exception("Connection failed")):
            with pytest.raises(RuntimeError, match="Failed to initialize database pool"):
                await db_pool.initialize()
            
            assert db_pool._initialized is False
            assert db_pool._pool is None


# =============================================================================
# Test DatabasePool.acquire()
# =============================================================================

class TestDatabasePoolAcquire:
    """Tests for DatabasePool.acquire() context manager."""

    @pytest.mark.asyncio
    async def test_acquire_success(self, db_pool):
        """Should acquire and release connection successfully."""
        mock_connection = MagicMock()
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        
        mock_acquire_ctx = AsyncMock()
        mock_acquire_ctx.__aenter__.return_value = mock_connection
        mock_acquire_ctx.__aexit__.return_value = None
        mock_pool.acquire.return_value = mock_acquire_ctx
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            async with db_pool.acquire() as connection:
                assert connection is mock_connection

    @pytest.mark.asyncio
    async def test_acquire_raises_when_not_initialized(self, db_pool):
        """Should raise RuntimeError when pool is not initialized."""
        with pytest.raises(RuntimeError, match="Database pool not initialized"):
            async with db_pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_acquire_context_manager_closes_connection(self, db_pool):
        """Should properly close connection when exiting context."""
        mock_connection = MagicMock()
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        
        mock_acquire_ctx = AsyncMock()
        mock_acquire_ctx.__aenter__.return_value = mock_connection
        mock_pool.acquire.return_value = mock_acquire_ctx
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            async with db_pool.acquire() as connection:
                pass
            
            mock_acquire_ctx.__aexit__.assert_called()


# =============================================================================
# Test DatabasePool.health_check()
# =============================================================================

class TestDatabasePoolHealthCheck:
    """Tests for DatabasePool.health_check() method."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, db_pool):
        """Should return True when health check passes."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        mock_connection = MagicMock()
        mock_connection.execute = AsyncMock()
        
        mock_acquire_ctx = AsyncMock()
        mock_acquire_ctx.__aenter__.return_value = mock_connection
        mock_acquire_ctx.__aexit__.return_value = None
        mock_pool.acquire.return_value = mock_acquire_ctx
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            result = await db_pool.health_check()
            
            assert result is True
            mock_connection.execute.assert_called_once_with("SELECT 1")

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_initialized(self, db_pool):
        """Should return False when pool is not initialized."""
        result = await db_pool.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_timeout(self, db_pool):
        """Should return False when query times out."""
        import asyncio
        
        mock_pool = AsyncMock()
        mock_connection = MagicMock()
        mock_connection.execute = AsyncMock(side_effect=asyncio.TimeoutError())
        
        acquire_ctx = mock_pool.acquire.return_value
        acquire_ctx.__aenter__.return_value = mock_connection
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            result = await db_pool.health_check()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_postgres_error(self, db_pool):
        """Should return False when Postgres error occurs."""
        mock_pool = AsyncMock()
        mock_connection = MagicMock()
        
        # Simulate asyncpg.PostgresError
        from asyncpg import PostgresError
        mock_connection.execute = AsyncMock(side_effect=PostgresError("error"))
        
        acquire_ctx = mock_pool.acquire.return_value
        acquire_ctx.__aenter__.return_value = mock_connection
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            result = await db_pool.health_check()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_generic_exception(self, db_pool):
        """Should return False on any generic exception."""
        mock_pool = AsyncMock()
        mock_connection = MagicMock()
        mock_connection.execute = AsyncMock(side_effect=Exception("Unexpected error"))
        
        acquire_ctx = mock_pool.acquire.return_value
        acquire_ctx.__aenter__.return_value = mock_connection
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            result = await db_pool.health_check()
            
            assert result is False


# =============================================================================
# Test DatabasePool.get_stats()
# =============================================================================

class TestDatabasePoolGetStats:
    """Tests for DatabasePool.get_stats() method."""

    @pytest.mark.asyncio
    async def test_get_stats_returns_correct_structure(self, db_pool):
        """Should return dict with correct keys."""
        mock_pool = MagicMock()
        mock_pool.get_size.return_value = 10
        mock_pool.get_idle_size.return_value = 7
        mock_pool.close = AsyncMock()
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            stats = db_pool.get_stats()
            
            assert "size" in stats
            assert "idle" in stats
            assert "used" in stats
            assert "max_size" in stats
            assert "min_size" in stats

    @pytest.mark.asyncio
    async def test_get_stats_returns_correct_values(self, db_pool):
        """Should return correct values in stats dict."""
        mock_pool = MagicMock()
        mock_pool.get_size.return_value = 10
        mock_pool.get_idle_size.return_value = 7
        mock_pool.close = AsyncMock()
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            stats = db_pool.get_stats()
            
            assert stats["size"] == 10
            assert stats["idle"] == 7
            assert stats["used"] == 3
            assert stats["max_size"] == 20
            assert stats["min_size"] == 10

    @pytest.mark.asyncio
    async def test_get_stats_returns_zeros_when_not_initialized(self, db_pool):
        """Should return zeros when pool is not initialized."""
        stats = db_pool.get_stats()
        
        assert stats["size"] == 0
        assert stats["idle"] == 0
        assert stats["used"] == 0
        assert stats["max_size"] == 20  # From config
        assert stats["min_size"] == 10  # From config

    @pytest.mark.asyncio
    async def test_get_stats_with_custom_config(self):
        """Should return correct max/min sizes from custom config."""
        config = PoolConfig(
            dsn="postgresql://test:test@localhost:5432/testdb",
            min_size=5,
            max_size=25
        )
        pool = DatabasePool(config=config)
        
        stats = pool.get_stats()
        
        assert stats["max_size"] == 25
        assert stats["min_size"] == 5


# =============================================================================
# Test is_initialized property
# =============================================================================

class TestIsInitialized:
    """Tests for DatabasePool.is_initialized property."""

    @pytest.mark.asyncio
    async def test_is_initialized_false_before_init(self, db_pool):
        """Should return False before initialization."""
        assert db_pool.is_initialized is False

    @pytest.mark.asyncio
    async def test_is_initialized_true_after_init(self, db_pool):
        """Should return True after successful initialization."""
        mock_pool = AsyncMock()
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            assert db_pool.is_initialized is True

    @pytest.mark.asyncio
    async def test_is_initialized_false_after_close(self, db_pool):
        """Should return False after closing the pool."""
        mock_pool = AsyncMock()
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            await db_pool.close()
            
            assert db_pool.is_initialized is False


# =============================================================================
# Test DatabasePool.close()
# =============================================================================

class TestDatabasePoolClose:
    """Tests for DatabasePool.close() method."""

    @pytest.mark.asyncio
    async def test_close_success(self, db_pool):
        """Should successfully close the pool."""
        mock_pool = AsyncMock()
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            await db_pool.close()
            
            assert db_pool._initialized is False
            assert db_pool._pool is None
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_when_not_initialized(self, db_pool):
        """Should handle closing when pool is not initialized."""
        await db_pool.close()
        
        assert db_pool._initialized is False
        assert db_pool._pool is None


class TestDatabasePoolReconnect:
    """Tests for DatabasePool._reconnect() method."""

    @pytest.mark.asyncio
    async def test_reconnect_success(self, db_pool):
        """Should successfully reconnect on first attempt."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_pool.initialize()
            
            await db_pool._reconnect()
            
            assert db_pool._initialized is True

    @pytest.mark.asyncio
    async def test_reconnect_with_retry(self, db_pool):
        """Should retry on connection failure and succeed."""
        from asyncpg import InterfaceError
        
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        
        call_count = [0]
        
        def create_pool_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise InterfaceError("Connection lost")
            return mock_pool
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, side_effect=create_pool_side_effect):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch.object(db_pool, '_initialized', False):
                    await db_pool._reconnect()
                    
                    assert call_count[0] == 3
                    assert db_pool._initialized is True

    @pytest.mark.asyncio
    async def test_reconnect_fails_after_max_attempts(self, db_pool):
        """Should raise ConnectionError after max retry attempts."""
        from asyncpg import InterfaceError
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock, side_effect=InterfaceError("Connection lost")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(ConnectionError, match="Failed to reconnect"):
                    await db_pool._reconnect()
                
                assert db_pool._initialized is False
                assert db_pool._pool is None


class TestGlobalPoolFunctions:
    """Tests for configure_pool, get_pool, and close_pool functions."""

    @pytest.mark.asyncio
    async def test_configure_pool_with_dsn(self):
        """Should configure global pool with provided DSN."""
        test_dsn = "postgresql://test:test@localhost:5432/testdb"
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool_instance = MagicMock()
            mock_pool_instance.close = AsyncMock()
            mock_create.return_value = mock_pool_instance
            
            with patch("tools.db_pool._pool", None):
                pool = await configure_pool(dsn=test_dsn)
                
                assert pool is not None
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pool_lazy_initialization(self, clean_env):
        """Should lazily initialize pool when calling get_pool."""
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_PASSWORD"] = "testpass"
        os.environ["POSTGRES_DB"] = "testdb"
        
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool_instance = MagicMock()
            mock_pool_instance.close = AsyncMock()
            mock_create.return_value = mock_pool_instance
            
            with patch("tools.db_pool._pool", None):
                pool = await get_pool()
                assert pool is not None

    @pytest.mark.asyncio
    async def test_close_pool_success(self):
        """Should close global pool successfully."""
        mock_pool_instance = MagicMock()
        mock_pool_instance.close = AsyncMock()
        
        with patch("tools.db_pool._pool", mock_pool_instance):
            await close_pool()
            
            mock_pool_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_pool_when_none(self):
        """Should handle closing when global pool is None."""
        with patch("tools.db_pool._pool", None):
            await close_pool()
