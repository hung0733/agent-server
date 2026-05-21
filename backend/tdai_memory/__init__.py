"""
tdai-memory: Multi-layer AI agent memory system.

Four-layer memory architecture:
    L0 — Raw conversation capture (PG + Qdrant)
    L1 — Structured memory extraction (persona/episodic/instruction)
    L2 — Scene block management
    L3 — Profile generation (persona.md / SOUL.md / IDENTITY.md)

Usage:
    from tdai_memory import MemoryManager, MemoryConfig, CompletedTurn

    config = MemoryConfig(
        postgres_url="postgresql://...",
        qdrant_url="http://localhost:6333",
        embedding_api_key="sk-...",
        embedding_model="text-embedding-3-small",
    )
    memory = MemoryManager(config, openai_client=client)
    await memory.initialize()

    # Before LLM turn
    result = await memory.recall(agent_id="my-agent", user_text="...", session_key="...")

    # After LLM turn
    await memory.capture(agent_id="my-agent", turn=turn)
"""

from .config import MemoryConfig
from .manager import MemoryManager
from .models import (
    CaptureResult,
    CompletedTurn,
    L0Record,
    MemoryRecord,
    MemorySearchParams,
    PipelineSessionState,
    RecallResult,
    RecalledMemory,
    SearchResult,
)

__all__ = [
    "MemoryManager",
    "MemoryConfig",
    "MemoryRecord",
    "L0Record",
    "CompletedTurn",
    "RecallResult",
    "RecalledMemory",
    "CaptureResult",
    "PipelineSessionState",
    "MemorySearchParams",
    "SearchResult",
]
