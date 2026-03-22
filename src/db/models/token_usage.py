# pyright: reportMissingImports=false
"""
Pydantic models for token usage tracking.

This module provides Pydantic v2 models for validation and serialization
of token usage data.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from db.models.base import BaseModelWithID
from db.types import gen_random_uuid


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
    """Model for creating a new token usage record.
    
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


class TokenUsage(TokenUsageBase, BaseModelWithID):
    """Complete token usage model with all database fields.
    
    Represents a full token usage record as stored in the database.
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
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )
