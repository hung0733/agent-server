"""Message queue type definitions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel


class QueueTaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueTaskPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    def as_int(self) -> int:
        """Higher int = higher priority (for ordering)."""
        return {"critical": 3, "high": 2, "normal": 1, "low": 0}[self.value]


class QueueTaskState(StrEnum):
    INIT = "init"
    COLLECTED_DB_DATA = "collected_db_data"
    PACKED_MEMORY = "packed_memory"
    MESSAGES_PACKED = "messages_packed"
    SELECTED_LLM_MODEL = "selected_llm_model"
    SENDING_TO_LLM = "sending_to_llm"
    WAITING_RESPONSE = "waiting_response"
    RECEIVING_STREAM = "receiving_stream"
    STREAMING_TO_CLIENT = "streaming_to_client"
    COMPLETED = "completed"
    ERROR = "error"


class StreamChunk(BaseModel):
    """A single chunk produced by an LLM stream."""

    chunk_type: str  # "content" | "think" | "tool" | "tool_result" | "done"
    content: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    timestamp: Optional[float] = None


class QueueStats(BaseModel):
    total_tasks: int
    pending_tasks: int
    processing_tasks: int
    completed_tasks: int
    failed_tasks: int
    cancelled_tasks: int
    avg_processing_time: Optional[float] = None
