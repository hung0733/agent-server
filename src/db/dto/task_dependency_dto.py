# pyright: reportMissingImports=false
"""
Pydantic DTOs for task dependencies.

This module provides Pydantic v2 DTOs for validation and serialization
of task dependency data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.task_dependency_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


# =============================================================================
# Task Dependency DTOs
# =============================================================================

class TaskDependencyBase(BaseModel):
    """Base model with common task dependency fields."""

    dependency_type: str = Field(
        default="sequential",
        description="Type of dependency: 'sequential', 'parallel', 'conditional'",
    )
    """Dependency type."""

    condition_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional condition for conditional dependencies",
    )
    """Condition configuration."""

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
        description="Parent task UUID",
    )
    """Parent task ID."""

    child_task_id: UUID = Field(
        ...,
        description="Child task UUID",
    )
    """Child task ID."""


class TaskDependencyUpdate(BaseModel):
    """DTO for updating an existing task dependency.

    All fields are optional - only provided fields will be updated.
    """

    id: UUID = Field(
        ...,
        description="Task dependency ID to update",
    )
    """Dependency ID."""

    dependency_type: Optional[str] = None
    condition_json: Optional[dict[str, Any]] = None

    model_config = ConfigDict(extra="ignore")


class TaskDependency(TaskDependencyBase):
    """Complete task dependency DTO with all fields.

    Used for output after database operations.
    Includes generated ID and timestamps.
    """

    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Task dependency UUID",
    )
    """Dependency ID."""

    parent_task_id: UUID = Field(
        ...,
        description="Parent task UUID",
    )
    """Parent task ID."""

    child_task_id: UUID = Field(
        ...,
        description="Child task UUID",
    )
    """Child task ID."""

    created_at: datetime = Field(
        default_factory=now_utc,
        description="Record creation timestamp (UTC)",
    )
    """Creation timestamp."""

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,  # Enable ORM mode for SQLAlchemy integration
    )
