# pyright: reportMissingImports=false
"""
Pydantic models for dead letter queue.

This module provides Pydantic v2 models for validation and serialization
of dead letter queue data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID
from db.types import gen_random_uuid


class DeadLetterQueueBase(BaseModel):
    """Base model with common dead letter queue fields."""
    
    original_task_id: Optional[UUID] = Field(
        default=None,
        description="ID of the original task (NULL if task was deleted)",
    )
    """Original task ID (nullable - task may be deleted)."""
    
    original_queue_entry_id: Optional[UUID] = Field(
        default=None,
        description="ID of the original queue entry",
    )
    """Original queue entry ID."""
    
    original_payload_json: dict[str, Any] = Field(
        ...,
        description="Full original record preserved for debugging and reprocessing",
    )
    """Complete original payload for potential reprocessing."""
    
    failure_reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Error type or classification",
    )
    """Classification of the failure (e.g., 'MaxRetriesExceeded')."""
    
    failure_details_json: dict[str, Any] = Field(
        ...,
        description="Full error context, stack traces, and debugging information",
    )
    """Detailed error information for troubleshooting."""
    
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of times moved to DLQ",
    )
    """Retry count tracking."""
    
    last_attempt_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last failed execution",
    )
    """Last failure timestamp."""
    
    is_active: bool = Field(
        default=True,
        description="Whether this DLQ item is unresolved",
    )
    """Active status (True = unresolved, False = addressed)."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "original_task_id": "550e8400-e29b-41d4-a716-446655440000",
                "original_queue_entry_id": "660f9500-f39c-51e5-b827-557766550001",
                "original_payload_json": {
                    "task_id": "550e8400-e29b-41d4-a716-446655440000",
                    "task_type": "research",
                    "payload": {"query": "AI developments"},
                },
                "failure_reason": "MaxRetriesExceeded",
                "failure_details_json": {
                    "error": "Connection timeout",
                    "stack_trace": "File \"app.py\", line 42...",
                    "retry_attempts": 3,
                },
                "retry_count": 3,
                "last_attempt_at": "2026-03-22T12:00:00Z",
                "is_active": True,
            }
        }
    )


class DeadLetterQueueCreate(DeadLetterQueueBase):
    """Model for creating a new DLQ entry.
    
    Used for input validation when moving failed tasks to the dead letter queue.
    """
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "original_task_id": "550e8400-e29b-41d4-a716-446655440000",
                "original_queue_entry_id": "660f9500-f39c-51e5-b827-557766550001",
                "original_payload_json": {
                    "task_id": "550e8400-e29b-41d4-a716-446655440000",
                    "task_type": "research",
                },
                "failure_reason": "MaxRetriesExceeded",
                "failure_details_json": {
                    "error": "Max retries exceeded",
                    "attempts": 3,
                },
                "retry_count": 3,
            }
        }
    )


class DeadLetterQueueResolve(BaseModel):
    """Model for resolving a DLQ entry.
    
    Used for admin intervention to mark DLQ items as resolved.
    Includes audit trail fields for tracking who resolved and when.
    """
    
    resolved_by: Optional[UUID] = Field(
        default=None,
        description="ID of the user who resolved this issue (NULL for system resolution)",
    )
    """User who performed the resolution (nullable for automated resolution)."""
    
    is_active: bool = Field(
        default=False,
        description="Set to False when resolving",
    )
    """Should be set to False when resolving."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "resolved_by": "770g0600-g40d-62f6-c938-668877660002",
                "is_active": False,
            }
        }
    )


class DeadLetterQueueUpdate(BaseModel):
    """Model for updating an existing DLQ entry.
    
    Used for partial updates to DLQ records.
    All fields are optional to allow partial updates.
    """
    
    original_task_id: Optional[UUID] = Field(
        default=None,
        description="Original task ID",
    )
    """Original task ID."""
    
    original_queue_entry_id: Optional[UUID] = Field(
        default=None,
        description="Original queue entry ID",
    )
    """Original queue entry ID."""
    
    failure_reason: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Error type or classification",
    )
    """Failure reason."""
    
    failure_details_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Error details",
    )
    """Failure details."""
    
    retry_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Retry count",
    )
    """Retry count."""
    
    last_attempt_at: Optional[datetime] = Field(
        default=None,
        description="Last attempt timestamp",
    )
    """Last attempt time."""
    
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="Resolution timestamp",
    )
    """When resolved."""
    
    resolved_by: Optional[UUID] = Field(
        default=None,
        description="User who resolved",
    )
    """Resolver user ID."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="Active status",
    )
    """Active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "resolved_at": "2026-03-22T14:00:00Z",
                "resolved_by": "770g0600-g40d-62f6-c938-668877660002",
                "is_active": False,
            }
        }
    )


class DeadLetterQueue(DeadLetterQueueBase, BaseModelWithID):
    """Complete dead letter queue model with all database fields.
    
    Represents a full DLQ entry record as stored in the database.
    """
    
    dead_lettered_at: datetime = Field(
        ...,
        description="When item was moved to dead letter queue",
    )
    """DLQ entry timestamp."""
    
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="When admin marked this issue as resolved",
    )
    """Resolution timestamp (NULL if unresolved)."""
    
    resolved_by: Optional[UUID] = Field(
        default=None,
        description="ID of user who resolved this (NULL if unresolved)",
    )
    """Resolver user ID (nullable - only set when resolved)."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "880h1700-h51e-73g7-d049-779988770003",
                "original_task_id": "550e8400-e29b-41d4-a716-446655440000",
                "original_queue_entry_id": "660f9500-f39c-51e5-b827-557766550001",
                "original_payload_json": {
                    "task_id": "550e8400-e29b-41d4-a716-446655440000",
                    "task_type": "research",
                    "payload": {"query": "AI developments"},
                },
                "failure_reason": "MaxRetriesExceeded",
                "failure_details_json": {
                    "error": "Connection timeout after 3 retries",
                    "stack_trace": "File \"app.py\", line 42...",
                    "retry_attempts": 3,
                },
                "retry_count": 3,
                "last_attempt_at": "2026-03-22T12:00:00Z",
                "dead_lettered_at": "2026-03-22T12:01:00Z",
                "resolved_at": "2026-03-22T14:00:00Z",
                "resolved_by": "770g0600-h51e-73g7-d049-779988770003",
                "is_active": False,
                "created_at": "2026-03-22T12:01:00Z",
                "updated_at": "2026-03-22T14:00:00Z",
            }
        }
    )
