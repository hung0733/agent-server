# pyright: reportMissingImports=false
"""
Tests for LangGraph checkpoint setup.

This module tests that the LangGraph checkpoint schema and related tables
are properly created by the GraphStore initialization.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text

from graph.graph_store import GraphStore


@pytest_asyncio.fixture
async def checkpointer():
    """Create and initialize GraphStore checkpointer."""
    checkpointer, pool = await GraphStore.init_langgraph_checkpointer()
    yield checkpointer
    await pool.close()


class TestCheckpointSetup:
    """Test LangGraph checkpoint table creation."""

    async def test_setup_checkpointer_creates_tables(self, checkpointer):
        """Test that GraphStore creates the langgraph tables."""
        # Verify checkpointer is created
        assert checkpointer is not None
        assert GraphStore.checkpointer is not None
        assert GraphStore.pool is not None

    async def test_langgraph_checkpoints_table_exists(self, checkpointer):
        """Test that langgraph.checkpoints table is created."""
        # Query to check if table exists
        async with GraphStore.pool.connection() as conn:
            result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'langgraph'
                        AND table_name = 'checkpoints'
                    )
                """)
            )
            exists = result.scalar()

        assert exists is True

    async def test_langgraph_checkpoint_blobs_table_exists(self, checkpointer):
        """Test that langgraph.checkpoint_blobs table is created."""
        # Query to check if table exists
        async with GraphStore.pool.connection() as conn:
            result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'langgraph'
                        AND table_name = 'checkpoint_blobs'
                    )
                """)
            )
            exists = result.scalar()

        assert exists is True

    async def test_langgraph_checkpoint_writes_table_exists(self, checkpointer):
        """Test that langgraph.checkpoint_writes table is created."""
        # Query to check if table exists
        async with GraphStore.pool.connection() as conn:
            result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'langgraph'
                        AND table_name = 'checkpoint_writes'
                    )
                """)
            )
            exists = result.scalar()

        assert exists is True

    async def test_langgraph_schema_exists(self, checkpointer):
        """Test that langgraph schema is created."""
        # Query to check if schema exists
        async with GraphStore.pool.connection() as conn:
            result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.schemata
                        WHERE schema_name = 'langgraph'
                    )
                """)
            )
            exists = result.scalar()

        assert exists is True


class TestCheckpointOperations:
    """Test basic checkpoint operations after setup."""

    async def test_checkpoint_put_and_get(self, checkpointer):
        """Test storing and retrieving a checkpoint."""
        write_config = {"configurable": {"thread_id": "test-1", "checkpoint_ns": ""}}
        read_config = {"configurable": {"thread_id": "test-1"}}

        checkpoint = {
            "v": 4,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": "1ef4f797-8335-6428-8001-8a1503f9b875",
            "channel_values": {
                "my_key": "test_value",
                "node": "node",
            },
            "channel_versions": {
                "__start__": 2,
                "my_key": 3,
                "start:node": 3,
                "node": 3,
            },
            "versions_seen": {
                "__input__": {},
                "__start__": {"__start__": 1},
                "node": {"start:node": 2},
            },
        }

        # Store checkpoint
        await checkpointer.aput(write_config, checkpoint, {}, {})

        # Load checkpoint
        loaded = await checkpointer.aget(read_config)

        assert loaded is not None
        assert loaded["channel_values"]["my_key"] == "test_value"

    async def test_checkpoint_list(self, checkpointer):
        """Test listing checkpoints."""
        write_config = {"configurable": {"thread_id": "test-2", "checkpoint_ns": ""}}

        # Create multiple checkpoints
        for i in range(3):
            checkpoint = {
                "v": 4,
                "ts": f"2024-07-31T20:14:{i:02d}.804150+00:00",
                "id": f"1ef4f797-8335-6428-8001-{i:012d}",
                "channel_values": {"my_key": f"value_{i}"},
                "channel_versions": {"__start__": i + 1},
                "versions_seen": {},
            }
            await checkpointer.aput(write_config, checkpoint, {}, {})

        # List checkpoints
        read_config = {"configurable": {"thread_id": "test-2"}}
        checkpoints = [c async for c in checkpointer.alist(read_config)]

        assert len(checkpoints) == 3
