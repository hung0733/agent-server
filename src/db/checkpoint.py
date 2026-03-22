"""LangGraph checkpoint setup utilities.

This module provides helper functions for setting up LangGraph's
PostgreSQL-based checkpoint storage system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


async def setup_checkpointer(dsn: str) -> AsyncPostgresSaver:
    """Create and configure a LangGraph AsyncPostgresSaver instance.
    
    This function creates an AsyncPostgresSaver instance from the provided
    DSN and calls asetup() to create the necessary langgraph tables
    (langgraph.checkpoints, langgraph.checkpoint_blobs, 
    langgraph.checkpoint_writes).
    
    Args:
        dsn: PostgreSQL DSN string in format:
             postgresql+asyncpg://user:password@host:port/database
             The connection should have server_settings with search_path
             containing 'langgraph,public' for proper schema resolution.
    
    Returns:
        AsyncPostgresSaver instance ready for checkpoint operations.
        The checkpointer.asetup() method is called automatically to create
        required tables.
    
    Example:
        from db import get_dsn
        from db.checkpoint import setup_checkpointer
        
        dsn = get_dsn()
        checkpointer = await setup_checkpointer(dsn)
        
        # Use checkpointer with LangGraph workflows
        async with checkpointer:
            await checkpointer.aput(config, checkpoint, metadata, pending_writes)
    
    Note:
        The checkpointer.asetup() method creates the following tables in the
        'langgraph' schema:
        - langgraph.checkpoints: Stores checkpoint data
        - langgraph.checkpoint_blobs: Stores binary blob data
        - langgraph.checkpoint_writes: Stores pending writes
    
    Raises:
        RuntimeError: If the langgraph schema cannot be created or accessed.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    
    # Create the checkpointer from connection string
    checkpointer = AsyncPostgresSaver.from_conn_string(dsn)
    
    await checkpointer.asetup()
    
    return checkpointer
