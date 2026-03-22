# pyright: reportMissingImports=false
"""
Pydantic models for task queue.

This module provides Pydantic v2 models for validation and serialization
of task queue data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID
from db.types import TaskStatus, gen_random_uuid


class TaskQueueBase(BaseModel):
    """Base model with common task queue fields."""
    
    status: TaskStatus = Field(
        default=TaskStatus.pending,
        description="Current queue status",
    )
    """Queue entry status."""
    
    priority: int = Field(
        default=0,
        ge=0,
        description="Task priority (higher = processed first)",
    )
    """Task priority level."""
    
    queued_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="Timestamp when task was added to queue",
    )
    """Queue entry timestamp."""
    
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="When task should become available for processing",
    )
    """Scheduled availability time."""
    
    started_at: Optional[datetime] = Field(
        default=None,
        description="Task execution start timestamp",
    )
    """Execution start time."""
    
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Task completion timestamp",
    )
    """Completion time."""
    
    claimed_by: Optional[UUID] = Field(
        default=None,
        description="ID of the claiming agent instance",
    )
    """Claiming agent ID."""
    
    claimed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when task was claimed",
    )
    """Claim timestamp."""
    
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of retry attempts made",
    )
    """Retry attempt count."""
    
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts allowed",
    )
    """Maximum retries."""
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if task failed",
    )
    """Error message."""
    
    result_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for task execution results",
    )
    """Task execution results."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "status": "pending",
                "priority": 10,
                "queued_at": "2026-03-22T12:00:00Z",
                "scheduled_at": None,
                "started_at": None,
                "completed_at": None,
                "claimed_by": None,
                "claimed_at": None,
                "retry_count": 0,
                "max_retries": 3,
                "error_message": None,
                "result_json": None,
            }
        }
    )


class TaskQueueCreate(TaskQueueBase):
    """Model for creating a new queue entry.
    
    Used for input validation when adding tasks to the queue.
    """
    
    task_id: UUID = Field(
        ...,
        description="ID of the task to queue",
    )
    """Foreign key to the task."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "pending",
                "priority": 10,
                "max_retries": 3,
            }
        }
    )


class TaskQueueUpdate(BaseModel):
    """Model for updating an existing queue entry.
    
    Used for input validation when updating queue entries.
    All fields are optional to allow partial updates.
    """
    
    status: Optional[TaskStatus] = Field(
        default=None,
        description="Current queue status",
    )
    """Queue status."""
    
    priority: Optional[int] = Field(
        default=None,
        ge=0,
        description="Task priority",
    )
    """Task priority."""
    
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Scheduled availability time",
    )
    """Scheduled time."""
    
    started_at: Optional[datetime] = Field(
        default=None,
        description="Execution start timestamp",
    )
    """Start time."""
    
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Completion timestamp",
    )
    """Completion time."""
    
    claimed_by: Optional[UUID] = Field(
        default=None,
        description="Claiming agent ID",
    )
    """Claiming agent."""
    
    claimed_at: Optional[datetime] = Field(
        default=None,
        description="Claim timestamp",
    )
    """Claim time."""
    
    retry_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Retry count",
    )
    """Retry count."""
    
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum retries",
    )
    """Max retries."""
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message",
    )
    """Error message."""
    
    result_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Task results",
    )
    """Task results."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "status": "running",
                "started_at": "2026-03-22T12:05:00Z",
                "claimed_by": "660f9500-f39c-51e5-b827-557766550001",
                "claimed_at": "2026-03-22T12:05:00Z",
            }
        }
    )


class TaskQueue(TaskQueueBase, BaseModelWithID):
    """Complete task queue model with all database fields.
    
    Represents a full queue entry record as stored in the database.
    """
    
    task_id: UUID = Field(
        ...,
        description="ID of the task",
    )
    """Foreign key to the task."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "priority": 10,
                "queued_at": "2026-03-22T12:00:00Z",
                "scheduled_at": None,
                "started_at": "2026-03-22T12:05:00Z",
                "completed_at": "2026-03-22T12:10:00Z",
                "claimed_by": "660f9500-f39c-51e5-b827-557766550001",
                "claimed_at": "2026-03-22T12:05:00Z",
                "retry_count": 0,
                "max_retries": 3,
                "error_message": None,
                "result_json": {"output": "Task completed successfully"},
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:10:00Z",
            }
        }
    )