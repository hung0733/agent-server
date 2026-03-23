# pyright: reportMissingImports=false
"""
Pydantic DTOs for tasks and task dependencies.

This module provides Pydantic v2 DTOs for validation and serialization
of task and task dependency data. Follows the Base/Create/Update/Complete pattern.

Import path: db.dto.task_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db.types import TaskStatus, Priority, DependencyType


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


# =============================================================================
# Task DTOs
# =============================================================================

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
    """DTO for creating a new task.
    
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
                "agent_id": None,
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
    """DTO for updating an existing task.
    
    All fields are optional to allow partial updates.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the task to update",
    )
    """ID of task to update (required)."""
    
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
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "status": "running",
                "started_at": "2026-03-22T12:00:00Z",
                "retry_count": 1,
            }
        }
    )


class Task(TaskBase):
    """Complete task DTO with all database fields.
    
    Represents a full task record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
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
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "agent_id": None,
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


# =============================================================================
# Task Dependency DTOs
# =============================================================================

class TaskDependencyBase(BaseModel):
    """Base model with common task dependency fields."""
    
    dependency_type: DependencyType = Field(
        default=DependencyType.sequential,
        description="Type of dependency: sequential, parallel, or conditional",
    )
    """Dependency type determining how tasks relate."""
    
    condition_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for conditional dependency logic (if/when clauses)",
    )
    """Condition logic for conditional dependencies."""
    
    @field_validator("dependency_type", mode="before")
    @classmethod
    def validate_dependency_type(cls, v: Any) -> DependencyType:
        """Validate and coerce dependency_type, case-insensitive.
        
        Args:
            v: The value to validate (string or DependencyType).
            
        Returns:
            DependencyType enum value.
            
        Raises:
            ValueError: If the value is not a valid dependency type.
        """
        if isinstance(v, DependencyType):
            return v
        
        if isinstance(v, str):
            # Case-insensitive matching
            v_lower = v.lower()
            for dep_type in DependencyType:
                if dep_type.value == v_lower:
                    return dep_type
            valid_values = [dt.value for dt in DependencyType]
            raise ValueError(
                f"Invalid dependency_type '{v}'. Must be one of: {valid_values}"
            )
        
        raise ValueError(f"dependency_type must be a string or DependencyType, got {type(v)}")
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "dependency_type": "sequential",
                "condition_json": None,
            }
        }
    )


class TaskDependencyCreate(TaskDependencyBase):
    """DTO for creating a new task dependency.
    
    Used for input validation when creating task dependencies.
    """
    
    parent_task_id: UUID = Field(
        ...,
        description="ID of the parent task (must complete first)",
    )
    """Foreign key to the parent task."""
    
    child_task_id: UUID = Field(
        ...,
        description="ID of the child task (depends on parent)",
    )
    """Foreign key to the child task."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "parent_task_id": "550e8400-e29b-41d4-a716-446655440000",
                "child_task_id": "660f9500-f39c-51e5-b827-557766550001",
                "dependency_type": "sequential",
                "condition_json": None,
            }
        }
    )


class TaskDependencyUpdate(BaseModel):
    """DTO for updating an existing task dependency.
    
    All fields are optional to allow partial updates.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the task dependency to update",
    )
    """ID of task dependency to update (required)."""
    
    dependency_type: Optional[DependencyType] = Field(
        default=None,
        description="Type of dependency",
    )
    """Dependency type."""
    
    condition_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Condition logic for conditional dependencies",
    )
    """Condition JSON."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class TaskDependency(TaskDependencyBase):
    """Complete task dependency DTO with all database fields.
    
    Represents a full task dependency record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
    parent_task_id: UUID = Field(
        ...,
        description="ID of the parent task (must complete first)",
    )
    """Foreign key to the parent task."""
    
    child_task_id: UUID = Field(
        ...,
        description="ID of the child task (depends on parent)",
    )
    """Foreign key to the child task."""
    
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
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "parent_task_id": "550e8400-e29b-41d4-a716-446655440000",
                "child_task_id": "660f9500-f39c-51e5-b827-557766550001",
                "dependency_type": "conditional",
                "condition_json": {
                    "condition": "success",
                    "expression": "parent.result.status == 'completed'"
                },
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )