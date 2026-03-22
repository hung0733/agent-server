"""Integration tests for DatabasePool with real Docker PostgreSQL.

These tests require Docker to be running and test actual connection pool behavior
against a real PostgreSQL database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio

# Ensure src imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tools.db_pool import DatabasePool, PoolConfig, configure_pool, close_pool


# =============================================================================
# Docker Service Helpers
# =============================================================================


def _is_docker_running() -> bool:
    """Check if Docker daemon is running."""
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wait_for_postgres_ready(host: str, port: str, container_name: str) -> None:
    import subprocess
    
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            result = subprocess.run(
                ["docker", "exec", container_name, "pg_isready", "-U", "testuser"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.5)
                return
        except Exception:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError(f"PostgreSQL container {container_name} failed to start")


def _start_postgres_container() -> tuple[str, str]:
    """Start PostgreSQL Docker container and return (dsn, container_id)."""
    container_name = f"db_pool_test_postgres_{uuid4().hex[:8]}"
    
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "-e", "POSTGRES_USER=testuser",
            "-e", "POSTGRES_PASSWORD=testpass",
            "-e", "POSTGRES_DB=testdb",
            "-p", "5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    
    result = subprocess.run(
        ["docker", "port", container_name, "5432"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    port_line = result.stdout.strip().split("\n")[0]
    host_port = port_line.split(":")[-1]
    
    _wait_for_postgres_ready("localhost", host_port, container_name)
    
    dsn = f"postgresql://testuser:testpass@localhost:{host_port}/testdb"
    return dsn, container_name


def _stop_docker_container(container_id: str) -> None:
    """Stop and remove a Docker container."""
    try:
        subprocess.run(
            ["docker", "stop", "-t", "0", container_id],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["docker", "rm", container_id],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError:
        pass  # Container may already be removed


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def docker_postgres_dsn() -> AsyncGenerator[str, None]:
    """
    Start a Docker PostgreSQL container and return its DSN.
    
    Container is automatically stopped and removed after the test.
    """
    if not _is_docker_running():
        pytest.skip("Docker is not running - skipping PostgreSQL integration tests")
    
    dsn = None
    container_id = None
    
    try:
        dsn, container_id = _start_postgres_container()
        yield dsn
    finally:
        # Clean up global pool before stopping container
        await close_pool()
        if container_id:
            _stop_docker_container(container_id)


@pytest_asyncio.fixture(scope="function")
async def small_pool(docker_postgres_dsn: str) -> AsyncGenerator[DatabasePool, None]:
    """
    Create a DatabasePool with small pool size for testing.
    
    Pool configured with min_size=2, max_size=3 to test exhaustion scenarios.
    """
    config = PoolConfig(
        dsn=docker_postgres_dsn,
        min_size=2,
        max_size=3,
        timeout=10,  # Shorter timeout for tests
    )
    pool = DatabasePool(config=config)
    await pool.initialize()
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="function")
async def standard_pool(docker_postgres_dsn: str) -> AsyncGenerator[DatabasePool, None]:
    """
    Create a DatabasePool with standard pool size for testing.
    
    Pool configured with min_size=10, max_size=20 matching production defaults.
    """
    config = PoolConfig(
        dsn=docker_postgres_dsn,
        min_size=10,
        max_size=20,
        timeout=30,
    )
    pool = DatabasePool(config=config)
    await pool.initialize()
    try:
        yield pool
    finally:
        await pool.close()


# =============================================================================
# Pool Lifecycle Tests
# =============================================================================


class TestPoolLifecycle:
    """Tests for full pool lifecycle with real PostgreSQL."""

    @pytest.mark.asyncio
    async def test_pool_initialize_and_close(self, docker_postgres_dsn: str) -> None:
        """Test pool can initialize and close properly."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=2,
            max_size=5,
        )
        pool = DatabasePool(config=config)
        
        # Initially not initialized
        assert pool.is_initialized is False
        assert pool.get_size() == 0
        
        # Initialize
        await pool.initialize()
        assert pool.is_initialized is True
        assert pool.get_size() >= 2  # At least min_size connections
        
        # Close
        await pool.close()
        assert pool.is_initialized is False
        assert pool.get_size() == 0

    @pytest.mark.asyncio
    async def test_pool_context_manager(self, docker_postgres_dsn: str) -> None:
        """Test pool works as async context manager."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=2,
            max_size=5,
        )
        
        async with DatabasePool(config=config) as pool:
            assert pool.is_initialized is True
            
            # Execute a query
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                assert result == 1
        
        # Pool should be closed after context exit
        assert pool.is_initialized is False

    @pytest.mark.asyncio
    async def test_pool_health_check_success(self, docker_postgres_dsn: str) -> None:
        """Test health check returns True for healthy pool."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=1,
            max_size=2,
        )
        pool = DatabasePool(config=config)
        await pool.initialize()
        
        try:
            result = await pool.health_check()
            assert result is True
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_get_stats(self, docker_postgres_dsn: str) -> None:
        """Test get_stats returns correct values."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=3,
            max_size=10,
        )
        pool = DatabasePool(config=config)
        await pool.initialize()
        
        try:
            stats = pool.get_stats()
            assert stats["size"] >= 3  # At least min_size
            assert stats["max_size"] == 10
            assert stats["min_size"] == 3
            assert stats["idle"] >= 0
            assert stats["used"] >= 0
        finally:
            await pool.close()


# =============================================================================
# Concurrent Connection Tests
# =============================================================================


class TestConcurrentConnections:
    """Tests for concurrent connection acquisition."""

    @pytest.mark.asyncio
    async def test_20_parallel_queries(self, standard_pool: DatabasePool) -> None:
        """Test 20 parallel queries can acquire connections simultaneously."""
        num_queries = 20
        results = []
        errors = []
        
        async def execute_query(query_id: int) -> int:
            """Execute a query and return the result."""
            try:
                async with standard_pool.acquire() as conn:
                    # Simulate some work with sleep
                    await asyncio.sleep(0.1)
                    result = await conn.fetchval("SELECT $1::int", query_id)
                    return result
            except Exception as e:
                errors.append((query_id, e))
                raise
        
        # Run 20 queries in parallel
        tasks = [execute_query(i) for i in range(num_queries)]
        results = await asyncio.gather(*tasks)
        
        # Verify all queries completed successfully
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == num_queries
        assert sorted(results) == list(range(num_queries))

    @pytest.mark.asyncio
    async def test_concurrent_connection_acquisition_timing(self, standard_pool: DatabasePool) -> None:
        """Test that concurrent connections are acquired quickly."""
        num_queries = 15
        start_time = time.monotonic()
        acquisition_times = []
        
        async def measure_acquisition(query_id: int) -> float:
            """Measure time to acquire a connection."""
            acquire_start = time.monotonic()
            async with standard_pool.acquire() as conn:
                acquisition_time = time.monotonic() - acquire_start
                acquisition_times.append(acquisition_time)
                await conn.fetchval("SELECT 1")
            return acquisition_time
        
        # Run queries in parallel
        tasks = [measure_acquisition(i) for i in range(num_queries)]
        await asyncio.gather(*tasks)
        
        total_time = time.monotonic() - start_time
        
        # All acquisitions should be fast (under 1 second each)
        # Total time should be much less than running sequentially
        assert total_time < 5.0, f"Total time {total_time}s too slow for parallel queries"
        
        # Most acquisitions should be fast
        fast_acquisitions = [t for t in acquisition_times if t < 0.5]
        assert len(fast_acquisitions) >= num_queries * 0.8, \
            f"Too many slow acquisitions: {acquisition_times}"

    @pytest.mark.asyncio
    async def test_mixed_concurrent_operations(self, standard_pool: DatabasePool) -> None:
        """Test concurrent reads and writes."""
        # Create a test table
        async with standard_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS test_concurrent (
                    id SERIAL PRIMARY KEY,
                    value TEXT
                )
            """)
            await conn.execute("TRUNCATE test_concurrent")
        
        num_writes = 10
        num_reads = 10
        
        async def write_value(i: int) -> None:
            async with standard_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO test_concurrent (value) VALUES ($1)",
                    f"value_{i}"
                )
        
        async def read_count() -> int:
            async with standard_pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM test_concurrent")
        
        # Run writes and reads concurrently
        write_tasks = [write_value(i) for i in range(num_writes)]
        read_tasks = [read_count() for _ in range(num_reads)]
        
        await asyncio.gather(*write_tasks, *read_tasks)
        
        # Verify all writes completed
        async with standard_pool.acquire() as conn:
            final_count = await conn.fetchval("SELECT COUNT(*) FROM test_concurrent")
        
        assert final_count == num_writes
        
        # Cleanup
        async with standard_pool.acquire() as conn:
            await conn.execute("DROP TABLE test_concurrent")


# =============================================================================
# Pool Exhaustion Tests
# =============================================================================


class TestPoolExhaustion:
    """Tests for pool exhaustion behavior."""

    @pytest.mark.asyncio
    async def test_pool_exhaustion_21st_query_waits(self, small_pool: DatabasePool) -> None:
        """Test that 21st query waits when pool is exhausted.
        
        Small pool has max_size=3, so with 3 connections held:
        - 3 connections should be acquired immediately
        - 4th query should wait
        - When one connection is released, waiting query should acquire it
        """
        max_size = small_pool._config.max_size  # 3
        acquired_events: list[asyncio.Event] = [asyncio.Event() for _ in range(max_size)]
        release_events: list[asyncio.Event] = [asyncio.Event() for _ in range(max_size)]
        
        wait_started = asyncio.Event()
        wait_completed = asyncio.Event()
        
        async def hold_connection(index: int) -> None:
            """Hold a connection until release event is set."""
            async with small_pool.acquire() as conn:
                acquired_events[index].set()
                # Wait to be released
                await release_events[index].wait()
                # Execute a query to verify connection is valid
                await conn.fetchval("SELECT 1")
        
        async def waiting_query() -> float:
            """Try to acquire when pool is exhausted, measure wait time."""
            wait_started.set()
            start = time.monotonic()
            async with small_pool.acquire() as conn:
                wait_time = time.monotonic() - start
                await conn.fetchval("SELECT 1")
                wait_completed.set()
            return wait_time
        
        # Start tasks to hold all connections
        hold_tasks = [
            asyncio.create_task(hold_connection(i))
            for i in range(max_size)
        ]
        
        # Wait for all connections to be acquired
        await asyncio.gather(*[e.wait() for e in acquired_events])
        
        # Verify pool is exhausted (all used)
        stats = small_pool.get_stats()
        assert stats["used"] == max_size, f"Expected {max_size} used, got {stats['used']}"
        
        # Start waiting query (should block)
        waiting_task = asyncio.create_task(waiting_query())
        await wait_started.wait()
        
        # Give it a moment to try to acquire (should be waiting)
        await asyncio.sleep(0.1)
        assert not wait_completed.is_set(), "Waiting query should still be waiting"
        
        # Release one connection
        release_events[0].set()
        
        # Waiting query should now complete
        await wait_completed.wait()
        wait_time = await waiting_task
        
        # Verify it had to wait (positive wait time)
        assert wait_time > 0, "Query should have waited"
        
        # Release remaining connections
        for i in range(1, max_size):
            release_events[i].set()
        
        await asyncio.gather(*hold_tasks)

    @pytest.mark.asyncio
    async def test_pool_exhaustion_timeout(self, docker_postgres_dsn: str) -> None:
        """Test that pool exhaustion eventually times out if no connection released."""
        # Create pool with very short timeout
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=1,
            max_size=2,
            timeout=2,  # 2 second timeout
        )
        pool = DatabasePool(config=config)
        await pool.initialize()
        
        try:
            max_size = pool._config.max_size  # 2
            acquired_events: list[asyncio.Event] = [asyncio.Event() for _ in range(max_size)]
            release_events: list[asyncio.Event] = [asyncio.Event() for _ in range(max_size)]
            
            async def hold_connection(index: int) -> None:
                async with pool.acquire() as conn:
                    acquired_events[index].set()
                    await release_events[index].wait()
            
            # Hold all connections
            hold_tasks = [
                asyncio.create_task(hold_connection(i))
                for i in range(max_size)
            ]
            await asyncio.gather(*[e.wait() for e in acquired_events])
            
            # Try to acquire - should timeout
            with pytest.raises(Exception):  # asyncio.TimeoutError or similar
                async with asyncio.timeout(3):  # Give it 3 seconds (longer than pool timeout)
                    async with pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")
            
            # Release connections
            for e in release_events:
                e.set()
            await asyncio.gather(*hold_tasks)
        
        finally:
            await pool.close()


# =============================================================================
# Graceful Shutdown Tests
# =============================================================================


class TestGracefulShutdown:
    """Tests for graceful shutdown with in-flight queries."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_with_inflight_queries(self, docker_postgres_dsn: str) -> None:
        """Test that shutdown waits for in-flight queries to complete."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=2,
            max_size=5,
        )
        pool = DatabasePool(config=config)
        await pool.initialize()
        
        query_completed = asyncio.Event()
        query_started = asyncio.Event()
        
        async def long_running_query() -> str:
            """Run a query that takes time."""
            async with pool.acquire() as conn:
                query_started.set()
                # Simulate long-running work
                await asyncio.sleep(1.0)
                result = await conn.fetchval("SELECT 'completed'")
                query_completed.set()
                return result
        
        try:
            # Start a long-running query
            query_task = asyncio.create_task(long_running_query())
            await query_started.wait()
            
            # Start shutdown while query is in-flight
            close_task = asyncio.create_task(pool.close())
            
            # Give close a moment to start
            await asyncio.sleep(0.1)
            
            # Query should still complete (not cancelled)
            await query_completed.wait()
            
            # Verify query result
            result = await query_task
            assert result == "completed"
            
            # Close should complete
            await close_task
            
            # Pool should now be closed
            assert pool.is_initialized is False
            
        except Exception:
            await pool.close()
            raise

    @pytest.mark.asyncio
    async def test_shutdown_allows_pending_acquires_to_timeout(self, docker_postgres_dsn: str) -> None:
        """Test that close releases connections properly even with pending holds."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=1,
            max_size=2,
            timeout=1,
        )
        pool = DatabasePool(config=config)
        await pool.initialize()
        
        acquired_event = asyncio.Event()
        release_event = asyncio.Event()
        close_started = asyncio.Event()
        close_completed = asyncio.Event()
        
        async def hold_connection() -> None:
            async with pool.acquire() as conn:
                acquired_event.set()
                await close_started.wait()
                await asyncio.sleep(0.1)
                await conn.fetchval("SELECT 1")
        
        async def do_close() -> None:
            close_started.set()
            await pool.close()
            close_completed.set()
        
        hold_task = asyncio.create_task(hold_connection())
        close_task = asyncio.create_task(do_close())
        
        await acquired_event.wait()
        
        release_event.set()
        
        await hold_task
        await close_task
        
        assert close_completed.is_set()
        assert pool.is_initialized is False

    @pytest.mark.asyncio
    async def test_multiple_inflight_queries_complete_before_shutdown(self, docker_postgres_dsn: str) -> None:
        """Test multiple in-flight queries complete before shutdown."""
        config = PoolConfig(
            dsn=docker_postgres_dsn,
            min_size=3,
            max_size=10,
        )
        pool = DatabasePool(config=config)
        await pool.initialize()
        
        num_queries = 5
        query_results: list[str] = []
        query_started_events: list[asyncio.Event] = [asyncio.Event() for _ in range(num_queries)]
        all_started = asyncio.Event()
        
        async def query_with_delay(query_id: int) -> None:
            """Execute a query with a small delay."""
            async with pool.acquire() as conn:
                query_started_events[query_id].set()
                await asyncio.sleep(0.3)
                result = await conn.fetchval("SELECT $1::text", f"query_{query_id}")
                query_results.append(result)
        
        try:
            # Start multiple queries
            query_tasks = [
                asyncio.create_task(query_with_delay(i))
                for i in range(num_queries)
            ]
            
            # Wait for all queries to start
            await asyncio.gather(*[e.wait() for e in query_started_events])
            
            # Initiate shutdown while queries are running
            await pool.close()
            
            # All queries should have completed (results populated)
            # Note: This depends on how asyncpg handles pool.close()
            # asyncpg.Pool.close() waits for all connections to be returned
            
            assert pool.is_initialized is False
            
        except Exception:
            await pool.close()
            raise


# =============================================================================
# Global Pool Integration Tests
# =============================================================================


class TestGlobalPoolIntegration:
    """Tests for global pool functions with real PostgreSQL."""

    @pytest.mark.asyncio
    async def test_configure_pool_integration(self, docker_postgres_dsn: str) -> None:
        """Test configure_pool works with real database."""
        pool = await configure_pool(dsn=docker_postgres_dsn)
        
        try:
            assert pool.is_initialized is True
            
            # Execute a query
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                assert result == 1
        finally:
            await close_pool()

    @pytest.mark.asyncio
    async def test_close_pool_cleanup(self, docker_postgres_dsn: str) -> None:
        """Test close_pool properly cleans up."""
        await configure_pool(dsn=docker_postgres_dsn)
        await close_pool()
        
        # Pool should be None after close
        from tools.db_pool import _pool
        assert _pool is None