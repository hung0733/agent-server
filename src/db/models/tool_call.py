# pyright: reportMissingImports=false
"""
Pydantic models for tool calls.

This module provides Pydantic v2 models for validation and serialization
of tool call data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID
from db.types import gen_random_uuid


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
    """Model for creating a new tool call.

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
    """Model for updating an existing tool call.

    Used for input validation when updating tool calls.
    All fields are optional to allow partial updates.
    """

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
                "status": "completed",
                "output": {"results": ["result1", "result2"]},
                "duration_ms": 1500,
            }
        }
    )


class ToolCall(ToolCallBase, BaseModelWithID):
    """Complete tool call model with all database fields.

    Represents a full tool call record as stored in the database.
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
