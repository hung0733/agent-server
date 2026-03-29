# pyright: reportMissingImports=false
"""
Pydantic DTOs for token usage tracking.

This module provides Pydantic v2 DTOs for validation and serialization
of token usage data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.token_usage_dto

Note: TokenUsage records are immutable (audit trail) - only created_at,
no updated_at field.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict

from db.types import gen_random_uuid


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class TokenUsageBase(BaseModel):
    """Base model with common token usage fields."""
    
    session_id: str = Field(
        ...,
        description="Session identifier for grouping related requests",
    )
    """Session ID."""
    
    model_name: str = Field(
        ...,
        description="Name of the LLM model used",
    )
    """LLM model name."""
    
    input_tokens: int = Field(
        ...,
        ge=0,
        description="Number of tokens in the input/prompt",
    )
    """Input token count."""
    
    output_tokens: int = Field(
        ...,
        ge=0,
        description="Number of tokens in the output/completion",
    )
    """Output token count."""
    
    total_tokens: int = Field(
        ...,
        ge=0,
        description="Total tokens used (input + output)",
    )
    """Total token count."""
    
    estimated_cost_usd: Decimal = Field(
        ...,
        description="Estimated cost in USD (6 decimal places)",
    )
    """Estimated cost in USD."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "session_id": "session-abc123",
                "model_name": "gpt-4",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "estimated_cost_usd": "0.004500",
            }
        }
    )


class TokenUsageCreate(TokenUsageBase):
    """DTO for creating a new token usage record.
    
    Used for input validation when creating token usage records.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the user who made the request",
    )
    """Foreign key to the user."""
    
    agent_id: UUID = Field(
        ...,
        description="ID of the agent instance that processed the request",
    )
    """Foreign key to the agent instance."""

    task_id: Optional[UUID] = Field(
        default=None,
        description="Optional ID of the originating task row",
    )
    """Optional foreign key to the task row."""

    llm_endpoint_id: Optional[UUID] = Field(
        default=None,
        description="Optional ID of the selected LLM endpoint",
    )
    """Optional foreign key to the selected LLM endpoint."""


class TokenUsageUpdate(BaseModel):
    """DTO for updating a token usage record.
    
    Note: Token usage records are typically immutable (audit trail).
    This DTO is provided for API consistency but updates should return None.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the token usage record to update",
    )
    """ID of record to update (required)."""
    
    total_tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description="Updated total token count",
    )
    """Updated total tokens (optional, but typically not used)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class TokenUsage(TokenUsageBase):
    """Complete token usage DTO with all database fields.
    
    Represents a full token usage record as stored in the database.
    Used as the return type from DAO methods.
    
    Note: Token usage records only have created_at (no updated_at)
    since they are immutable audit records.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
    user_id: UUID = Field(
        ...,
        description="ID of the user who made the request",
    )
    """Foreign key to the user."""
    
    agent_id: UUID = Field(
        ...,
        description="ID of the agent instance that processed the request",
    )
    """Foreign key to the agent instance."""

    task_id: Optional[UUID] = Field(
        default=None,
        description="Optional ID of the originating task row",
    )
    """Optional foreign key to the task row."""

    llm_endpoint_id: Optional[UUID] = Field(
        default=None,
        description="Optional ID of the selected LLM endpoint",
    )
    """Optional foreign key to the selected LLM endpoint."""
    
    created_at: datetime = Field(
        default_factory=now_utc,
        description="Record creation timestamp (UTC)",
    )
    """Timestamp when the record was created (UTC timezone)."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "660f9500-f39c-51e5-b827-557766550001",
                "agent_id": "770g0600-g40d-62f6-c938-668877660002",
                "session_id": "session-abc123",
                "model_name": "gpt-4",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "estimated_cost_usd": "0.004500",
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )
