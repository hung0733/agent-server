from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StreamChunk(BaseModel):
    """A single chunk produced by an LLM stream."""

    chunk_type: str
    content: str | None = None
    data: dict[str, Any] | None = None
    timestamp: float | None = None
