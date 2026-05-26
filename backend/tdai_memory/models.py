"""Pydantic models for the TDAI memory system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# ───────────────────────────────────────
# Memory types
# ───────────────────────────────────────

MemoryType = Literal["persona", "episodic", "instruction"]


class EpisodicMetadata(BaseModel):
    activity_start_time: str | None = None  # ISO 8601, e.g. "2024-01-01T00:00:00+08:00"
    activity_end_time: str | None = None  # ISO 8601


# ───────────────────────────────────────
# L0: Raw conversation record
# ───────────────────────────────────────


class L0Record(BaseModel):
    """A single raw conversation message indexed for vector search."""

    id: str
    agent_id: str
    session_key: str
    session_id: str = ""
    role: Literal["user", "assistant"]
    message_text: str
    recorded_at: str  # ISO 8601
    timestamp: int  # epoch ms


# ───────────────────────────────────────
# L1: Structured memory record
# ───────────────────────────────────────


class MemoryRecord(BaseModel):
    """Structured memory extracted from conversations (L1)."""

    id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:12]}")
    agent_id: str
    content: str
    type: MemoryType
    priority: int = Field(
        default=0, ge=-1, le=100, description="0-100, -1 = strict global instruction"
    )
    scene_name: str = ""
    source_message_ids: list[str] = Field(default_factory=list)
    metadata: EpisodicMetadata | dict[str, Any] = Field(default_factory=dict)
    timestamps: list[str] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    session_key: str = ""
    session_id: str = ""


class RecalledMemory(BaseModel):
    """A memory returned from the recall search."""

    id: str
    content: str
    type: str
    score: float
    scene_name: str = ""
    priority: int = 0
    timestamps: list[str] = Field(default_factory=list)


# ───────────────────────────────────────
# Completed Turn (passed to capture)
# ───────────────────────────────────────


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: int


class ToolCallMessage(BaseModel):
    tool_call_id: str
    tool_name: str
    tool_input: dict
    tool_result: str
    timestamp: int


class CompletedTurn(BaseModel):
    """A completed conversation turn passed to the capture hook."""

    user_text: str
    assistant_text: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    tool_call: list[ToolCallMessage] = Field(default_factory=list)
    session_key: str
    session_id: str = ""
    started_at: int | None = None  # epoch ms
    original_user_message_count: int | None = None


# ───────────────────────────────────────
# Recall result
# ───────────────────────────────────────


class RecallResult(BaseModel):
    """Result from the auto-recall hook."""

    prepend_context: str | None = None  # Dynamic L1 memories for user prompt
    append_system_context: str | None = (
        None  # Stable persona + SOUL + IDENTITY + scenes
    )
    recalled_l1_memories: list[RecalledMemory] = Field(default_factory=list)
    recalled_l3_persona: str | None = None
    recalled_l3_soul: str | None = None
    recalled_l3_identity: str | None = None
    recall_strategy: str = "hybrid"
    context_timeline: list[dict] | None = None


# ───────────────────────────────────────
# Capture result
# ───────────────────────────────────────


class CaptureResult(BaseModel):
    """Result from the auto-capture hook."""

    scheduler_notified: bool = False
    l0_recorded_count: int = 0
    l0_vectors_written: int = 0
    filtered_messages: list[ConversationMessage] = Field(default_factory=list)


# ───────────────────────────────────────
# Pipeline state
# ───────────────────────────────────────


class PipelineSessionState(BaseModel):
    """Per-session pipeline state (extraction triggers, warmup)."""

    agent_id: str = ""
    session_key: str = ""
    conversation_count: int = 0
    last_extraction_time: str | None = None  # ISO
    last_extraction_updated_time: str | None = None  # ISO cursor for incremental L2
    last_active_time: int = 0  # epoch ms
    l2_pending_l1_count: int = 0
    warmup_threshold: int = 1  # 0=graduated, 1/2/4/8/etc=in warmup
    l2_last_extraction_time: str | None = None


# ───────────────────────────────────────
# Search
# ───────────────────────────────────────


class MemorySearchParams(BaseModel):
    """Parameters for memory search."""

    query: str
    agent_id: str
    top_k: int = 5
    strategy: Literal["embedding", "keyword", "hybrid"] = "hybrid"
    score_threshold: float = 0.3
    type_filter: MemoryType | None = None
    scene_filter: str | None = None


class ConversationSearchParams(BaseModel):
    """Parameters for conversation search."""

    query: str
    agent_id: str
    top_k: int = 5
    session_key: str | None = None


class SearchResult(BaseModel):
    """Generic search result."""

    text: str
    total: int
    strategy: str = "hybrid"
    items: list[dict[str, Any]] = Field(default_factory=list)
