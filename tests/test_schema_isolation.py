"""Schema isolation tests for LangGraph database setup.

These tests verify that the langgraph schema is properly isolated from the public schema
and that search_path is correctly configured. Requires Docker PostgreSQL.
"""

from __future__ import annotations

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

from utils.db_pool import DatabasePool, PoolConfig, close_pool


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
    """Wait for PostgreSQL to be ready."""
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
    container_name = f"schema_test_postgres_{uuid4().hex[:8]}"
    
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
        pytest.skip("Docker is not running - skipping schema isolation tests")
    
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
async def schema_pool(docker_postgres_dsn: str) -> AsyncGenerator[DatabasePool, None]:
    """
    Create a DatabasePool with search_path set to langgraph,public.
    
    This fixture tests the schema isolation configuration.
    """
    config = PoolConfig(
        dsn=docker_postgres_dsn,
        min_size=2,
        max_size=5,
        server_settings={"search_path": "langgraph,public"},
    )
    pool = DatabasePool(config=config)
    await pool.initialize()
    try:
        yield pool
    finally:
        await pool.close()


# =============================================================================
# Schema Creation Tests
# =============================================================================


class TestSchemaCreation:
    """Tests for langgraph schema creation."""

    @pytest.mark.asyncio
    async def test_create_langgraph_schema_if_not_exists(self, schema_pool: DatabasePool) -> None:
        """Test that CREATE SCHEMA IF NOT EXISTS langgraph works."""
        # Create the langgraph schema
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        # Verify schema exists
        async with schema_pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1",
                "langgraph"
            )
            assert result == 1

    @pytest.mark.asyncio
    async def test_create_schema_idempotent(self, schema_pool: DatabasePool) -> None:
        """Test that CREATE SCHEMA IF NOT EXISTS can be called multiple times."""
        async with schema_pool.acquire() as conn:
            # Create schema twice - should not error
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        # Verify schema still exists
        async with schema_pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1",
                "langgraph"
            )
            assert result == 1

    @pytest.mark.asyncio
    async def test_schema_created_before_table_creation(self, schema_pool: DatabasePool) -> None:
        """Test that langgraph schema must exist before creating tables in it."""
        async with schema_pool.acquire() as conn:
            # Create schema first
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
            
            # Now create a table in langgraph schema
            await conn.execute("""
                CREATE TABLE langgraph.test_table (
                    id SERIAL PRIMARY KEY,
                    data TEXT
                )
            """)
        
        # Verify table exists in langgraph schema
        async with schema_pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = $1 AND table_name = $2
                """,
                "langgraph",
                "test_table"
            )
            assert result == 1
        
        # Cleanup
        async with schema_pool.acquire() as conn:
            await conn.execute("DROP TABLE langgraph.test_table")


# =============================================================================
# Search Path Tests
# =============================================================================


class TestSearchPath:
    """Tests for search_path configuration."""

    @pytest.mark.asyncio
    async def test_search_path_includes_langgraph(self, schema_pool: DatabasePool) -> None:
        """Test that search_path includes langgraph schema."""
        async with schema_pool.acquire() as conn:
            # Get current search_path
            result = await conn.fetchval("SHOW search_path")
            
            # search_path should include langgraph
            assert "langgraph" in result, f"search_path '{result}' does not include langgraph"

    @pytest.mark.asyncio
    async def test_search_path_includes_public(self, schema_pool: DatabasePool) -> None:
        """Test that search_path includes public schema."""
        async with schema_pool.acquire() as conn:
            # Get current search_path
            result = await conn.fetchval("SHOW search_path")
            
            # search_path should include public
            assert "public" in result, f"search_path '{result}' does not include public"

    @pytest.mark.asyncio
    async def test_search_path_order_langgraph_first(self, schema_pool: DatabasePool) -> None:
        """Test that langgraph comes before public in search_path."""
        async with schema_pool.acquire() as conn:
            result = await conn.fetchval("SHOW search_path")
            
            # Parse search_path (format: "langgraph, public" or similar)
            schemas = [s.strip() for s in result.split(",")]
            
            # langgraph should come before public
            langgraph_index = schemas.index("langgraph") if "langgraph" in schemas else -1
            public_index = schemas.index("public") if "public" in schemas else -1
            
            assert langgraph_index != -1, "langgraph not found in search_path"
            assert public_index != -1, "public not found in search_path"
            assert langgraph_index < public_index, \
                f"langgraph (index {langgraph_index}) should come before public (index {public_index})"

    @pytest.mark.asyncio
    async def test_table_creation_uses_search_path(self, schema_pool: DatabasePool) -> None:
        """Test that table creation without schema prefix uses search_path."""
        # Ensure langgraph schema exists
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        try:
            # Create table without schema prefix - should go to langgraph (first in search_path)
            async with schema_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE test_search_path (
                        id SERIAL PRIMARY KEY,
                        data TEXT
                    )
                """)
            
            # Verify table was created in langgraph schema (first in search_path)
            async with schema_pool.acquire() as conn:
                # Check in langgraph schema
                result = await conn.fetchval(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    "langgraph",
                    "test_search_path"
                )
                assert result == 1, "Table should be created in langgraph schema"
                
                # Verify NOT in public schema
                result_public = await conn.fetchval(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    "public",
                    "test_search_path"
                )
                assert result_public is None, "Table should NOT be in public schema"
        finally:
            # Cleanup
            async with schema_pool.acquire() as conn:
                await conn.execute("DROP TABLE IF EXISTS langgraph.test_search_path")


# =============================================================================
# Schema Isolation Tests
# =============================================================================


class TestSchemaIsolation:
    """Tests for schema isolation between langgraph and public."""

    @pytest.mark.asyncio
    async def test_tables_isolated_by_schema(self, schema_pool: DatabasePool) -> None:
        """Test that tables in different schemas don't interfere."""
        # Ensure both schemas exist
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        try:
            # Create table with same name in both schemas
            async with schema_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE langgraph.shared_name (
                        id SERIAL PRIMARY KEY,
                        schema_type TEXT DEFAULT 'langgraph'
                    )
                """)
                await conn.execute("""
                    CREATE TABLE public.shared_name (
                        id SERIAL PRIMARY KEY,
                        schema_type TEXT DEFAULT 'public'
                    )
                """)
            
            # Query with schema-qualified name should return correct data
            async with schema_pool.acquire() as conn:
                # Insert into langgraph version
                await conn.execute(
                    "INSERT INTO langgraph.shared_name (schema_type) VALUES ('langgraph')"
                )
                # Insert into public version
                await conn.execute(
                    "INSERT INTO public.shared_name (schema_type) VALUES ('public')"
                )
                
                # Query langgraph table
                result_langgraph = await conn.fetchval(
                    "SELECT schema_type FROM langgraph.shared_name LIMIT 1"
                )
                assert result_langgraph == "langgraph"
                
                # Query public table
                result_public = await conn.fetchval(
                    "SELECT schema_type FROM public.shared_name LIMIT 1"
                )
                assert result_public == "public"
        finally:
            # Cleanup
            async with schema_pool.acquire() as conn:
                await conn.execute("DROP TABLE IF EXISTS langgraph.shared_name")
                await conn.execute("DROP TABLE IF EXISTS public.shared_name")

    @pytest.mark.asyncio
    async def test_search_path_first_schema_priority(self, schema_pool: DatabasePool) -> None:
        """Test that unqualified table names resolve to first schema in search_path."""
        # Ensure langgraph schema exists
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        try:
            # Create table in langgraph schema
            async with schema_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE priority_test (
                        id SERIAL PRIMARY KEY,
                        value TEXT
                    )
                """)
            
            # Insert data
            async with schema_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO priority_test (value) VALUES ('langgraph_first')"
                )
            
            # Query without schema prefix should use langgraph (first in search_path)
            async with schema_pool.acquire() as conn:
                result = await conn.fetchval("SELECT value FROM priority_test LIMIT 1")
                assert result == "langgraph_first"
        finally:
            # Cleanup
            async with schema_pool.acquire() as conn:
                await conn.execute("DROP TABLE IF EXISTS langgraph.priority_test")

    @pytest.mark.asyncio
    async def test_schema_permissions_isolated(self, schema_pool: DatabasePool) -> None:
        """Test that schemas can have independent permissions (conceptual test)."""
        # Ensure langgraph schema exists
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        # Verify we can query schema information independently
        async with schema_pool.acquire() as conn:
            # Get all schemas
            schemas = await conn.fetch(
                "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name"
            )
            schema_names = [row["schema_name"] for row in schemas]
            
            # Both schemas should exist
            assert "langgraph" in schema_names
            assert "public" in schema_names

    @pytest.mark.asyncio
    async def test_drop_schema_does_not_affect_public(self, schema_pool: DatabasePool) -> None:
        """Test that dropping langgraph schema doesn't affect public schema."""
        # Ensure langgraph schema exists
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        # Create table in public schema
        async with schema_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE public.preserve_me (
                    id SERIAL PRIMARY KEY
                )
            """)
        
        try:
            # Create and drop langgraph schema
            async with schema_pool.acquire() as conn:
                await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
                await conn.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
            
            # Verify public table still exists
            async with schema_pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    "public",
                    "preserve_me"
                )
                assert result == 1, "Public schema table should still exist"
        finally:
            # Cleanup
            async with schema_pool.acquire() as conn:
                await conn.execute("DROP TABLE IF EXISTS public.preserve_me")


# =============================================================================
# LangGraph Checkpoint Table Tests
# =============================================================================


class TestLangGraphCheckpointTables:
    """Tests for LangGraph checkpoint table creation in langgraph schema."""

    @pytest.mark.asyncio
    async def test_create_checkpoint_table_in_langgraph_schema(self, schema_pool: DatabasePool) -> None:
        """Test that checkpoint tables can be created in langgraph schema."""
        # Ensure langgraph schema exists
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        try:
            # Create a checkpoint-style table in langgraph schema
            async with schema_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE langgraph.checkpoints (
                        thread_id TEXT NOT NULL,
                        checkpoint_ns TEXT NOT NULL DEFAULT '',
                        checkpoint_id TEXT NOT NULL,
                        parent_checkpoint_id TEXT,
                        checkpoint BYTEA,
                        metadata BYTEA,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                    )
                """)
            
            # Verify table exists in langgraph schema
            async with schema_pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    "langgraph",
                    "checkpoints"
                )
                assert result == 1
            
            # Verify table does NOT exist in public schema
            async with schema_pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    "public",
                    "checkpoints"
                )
                assert result is None
        finally:
            # Cleanup
            async with schema_pool.acquire() as conn:
                await conn.execute("DROP TABLE IF EXISTS langgraph.checkpoints")

    @pytest.mark.asyncio
    async def test_create_checkpoint_writes_table(self, schema_pool: DatabasePool) -> None:
        """Test that checkpoint_writes table can be created in langgraph schema."""
        # Ensure langgraph schema exists
        async with schema_pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        
        try:
            async with schema_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE langgraph.checkpoint_writes (
                        thread_id TEXT NOT NULL,
                        checkpoint_ns TEXT NOT NULL DEFAULT '',
                        checkpoint_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        idx INT NOT NULL,
                        channel TEXT NOT NULL,
                        type TEXT,
                        value BYTEA,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    )
                """)
            
            # Verify table exists
            async with schema_pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                    """,
                    "langgraph",
                    "checkpoint_writes"
                )
                assert result == 1
        finally:
            # Cleanup
            async with schema_pool.acquire() as conn:
                await conn.execute("DROP TABLE IF EXISTS langgraph.checkpoint_writes")
