# pyright: reportMissingImports=false
"""
Pydantic models for tasks.

This module provides Pydantic v2 models for validation and serialization
of task data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID
from db.types import TaskStatus, Priority, gen_random_uuid


class TaskBase(BaseModel):
    """Base model with common task fields."""
    
    task_type: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Type of task (e.g., 'research', 'analysis', 'code_generation')",
    )
    """Type of task."""
    
    status: TaskStatus = Field(
        default=TaskStatus.pending,
        description="Current execution status",
    )
    """Task execution status."""
    
    priority: Priority = Field(
        default=Priority.normal,
        description="Task priority level for scheduling",
    )
    """Task priority level."""
    
    payload: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for task specifications and input parameters",
    )
    """Task specifications and input parameters."""
    
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for task execution results",
    )
    """Task execution results."""
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if task execution failed",
    )
    """Error message for failed tasks."""
    
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of retry attempts made",
    )
    """Number of retry attempts."""
    
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum number of retry attempts allowed",
    )
    """Maximum retry attempts."""
    
    session_id: Optional[str] = Field(
        default=None,
        max_length=500,
        description="LangGraph thread_id for checkpoint integration",
    )
    """LangGraph session/thread identifier."""
    
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Scheduled execution timestamp for temporal scheduling",
    )
    """Scheduled execution time."""
    
    started_at: Optional[datetime] = Field(
        default=None,
        description="Task execution start timestamp",
    )
    """Task start time."""
    
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Task completion timestamp",
    )
    """Task completion time."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "task_type": "research",
                "status": "pending",
                "priority": "normal",
                "payload": {"query": "latest AI developments", "max_results": 5},
                "result": None,
                "error_message": None,
                "retry_count": 0,
                "max_retries": 3,
                "session_id": "thread-abc123",
                "scheduled_at": None,
                "started_at": None,
                "completed_at": None,
            }
        }
    )


class TaskCreate(TaskBase):
    """Model for creating a new task.
    
    Used for input validation when creating tasks.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
    agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the executing agent instance",
    )
    """Foreign key to the agent instance."""
    
    parent_task_id: Optional[UUID] = Field(
        default=None,
        description="ID of the parent task for hierarchical decomposition",
    )
    """Parent task ID for task hierarchies."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "agent_id": "660f9500-f39c-51e5-b827-557766550001",
                "parent_task_id": None,
                "task_type": "research",
                "status": "pending",
                "priority": "normal",
                "payload": {"query": "latest AI developments"},
                "max_retries": 3,
            }
        }
    )


class TaskUpdate(BaseModel):
    """Model for updating an existing task.
    
    Used for input validation when updating tasks.
    All fields are optional to allow partial updates.
    """
    
    agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the executing agent instance",
    )
    """Agent instance ID."""
    
    status: Optional[TaskStatus] = Field(
        default=None,
        description="Current execution status",
    )
    """Task status."""
    
    priority: Optional[Priority] = Field(
        default=None,
        description="Task priority level",
    )
    """Task priority."""
    
    payload: Optional[dict[str, Any]] = Field(
        default=None,
        description="Task specifications and input parameters",
    )
    """Task payload."""
    
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Task execution results",
    )
    """Task result."""
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message for failed tasks",
    )
    """Error message."""
    
    retry_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of retry attempts",
    )
    """Retry count."""
    
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum retry attempts",
    )
    """Max retries."""
    
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Scheduled execution timestamp",
    )
    """Scheduled time."""
    
    started_at: Optional[datetime] = Field(
        default=None,
        description="Task start timestamp",
    )
    """Start time."""
    
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Task completion timestamp",
    )
    """Completion time."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "status": "running",
                "started_at": "2026-03-22T12:00:00Z",
                "retry_count": 1,
            }
        }
    )


class Task(TaskBase, BaseModelWithID):
    """Complete task model with all database fields.
    
    Represents a full task record as stored in the database.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
    agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the executing agent instance",
    )
    """Foreign key to the agent instance."""
    
    parent_task_id: Optional[UUID] = Field(
        default=None,
        description="ID of the parent task for hierarchical decomposition",
    )
    """Parent task ID."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "agent_id": "660f9500-f39c-51e5-b827-557766550001",
                "parent_task_id": None,
                "task_type": "research",
                "status": "completed",
                "priority": "high",
                "payload": {"query": "latest AI developments", "max_results": 5},
                "result": {"findings": ["finding1", "finding2"], "sources": 3},
                "error_message": None,
                "retry_count": 0,
                "max_retries": 3,
                "session_id": "thread-abc123",
                "scheduled_at": None,
                "started_at": "2026-03-22T12:00:00Z",
                "completed_at": "2026-03-22T12:05:00Z",
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:05:00Z",
            }
        }
    )
