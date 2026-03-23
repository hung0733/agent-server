# pyright: reportMissingImports=false
"""
Pydantic DTOs for tool calls.

This module provides Pydantic v2 DTOs for validation and serialization
of tool call data. Follows the Base/Create/Update/Complete pattern.

Import path: db.dto.tool_call_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


class ToolCallBase(BaseModel):
    """Base model with common tool call fields."""
    
    input: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for tool call input parameters",
    )
    """Tool call input parameters."""
    
    output: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for tool call output/results",
    )
    """Tool call output/results."""
    
    status: str = Field(
        default="pending",
        description="Execution status (pending, running, completed, failed)",
    )
    """Tool call execution status."""
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if tool call execution failed",
    )
    """Error message for failed tool calls."""
    
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Execution duration in milliseconds",
    )
    """Execution duration in milliseconds."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "input": {"query": "latest AI developments", "max_results": 5},
                "output": {"results": ["result1", "result2"], "sources": 3},
                "status": "completed",
                "error_message": None,
                "duration_ms": 1500,
            }
        }
    )


class ToolCallCreate(ToolCallBase):
    """DTO for creating a new tool call.
    
    Used for input validation when creating tool calls.
    """
    
    task_id: UUID = Field(
        ...,
        description="ID of the task that made this tool call",
    )
    """Foreign key to the task."""
    
    tool_id: UUID = Field(
        ...,
        description="ID of the tool that was called",
    )
    """Foreign key to the tool."""
    
    tool_version_id: Optional[UUID] = Field(
        default=None,
        description="ID of the specific tool version used",
    )
    """Foreign key to the tool version."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "tool_id": "660f9500-f39c-51e5-b827-557766550001",
                "tool_version_id": "770g0600-g40d-62f6-c938-668877660002",
                "input": {"query": "latest AI developments"},
                "status": "pending",
            }
        }
    )


class ToolCallUpdate(BaseModel):
    """DTO for updating an existing tool call.
    
    All fields are optional to allow partial updates.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the tool call to update",
    )
    """ID of tool call to update (required)."""
    
    input: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool call input parameters",
    )
    """Input parameters."""
    
    output: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool call output/results",
    )
    """Output/results."""
    
    status: Optional[str] = Field(
        default=None,
        description="Execution status",
    )
    """Status."""
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message",
    )
    """Error message."""
    
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Execution duration in milliseconds",
    )
    """Duration in milliseconds."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "880h1700-h51e-73g7-d049-779988770003",
                "status": "completed",
                "output": {"results": ["result1", "result2"]},
                "duration_ms": 1500,
            }
        }
    )


class ToolCall(ToolCallBase):
    """Complete tool call DTO with all database fields.
    
    Represents a full tool call record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
    task_id: UUID = Field(
        ...,
        description="ID of the task that made this tool call",
    )
    """Foreign key to the task."""
    
    tool_id: UUID = Field(
        ...,
        description="ID of the tool that was called",
    )
    """Foreign key to the tool."""
    
    tool_version_id: Optional[UUID] = Field(
        default=None,
        description="ID of the specific tool version used",
    )
    """Foreign key to the tool version."""
    
    created_at: datetime = Field(
        default_factory=now_utc,
        description="Record creation timestamp (UTC)",
    )
    """Timestamp when the record was created (UTC timezone)."""
    
    updated_at: datetime = Field(
        default_factory=now_utc,
        description="Last update timestamp (UTC)",
    )
    """Timestamp when the record was last updated (UTC timezone)."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "880h1700-h51e-73g7-d049-779988770003",
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "tool_id": "660f9500-f39c-51e5-b827-557766550001",
                "tool_version_id": "770g0600-g40d-62f6-c938-668877660002",
                "input": {"query": "latest AI developments", "max_results": 5},
                "output": {"results": ["result1", "result2"], "sources": 3},
                "status": "completed",
                "error_message": None,
                "duration_ms": 1500,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:01Z",
            }
        }
    )