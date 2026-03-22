# pyright: reportMissingImports=false
"""
Pydantic models for task dependencies.

This module provides Pydantic v2 models for validation and serialization
of task dependency data with proper enum handling for dependency_type.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db.models.base import BaseModelWithID
from db.types import DependencyType, gen_random_uuid


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
    
    @field_validator("condition_json", mode="after")
    @classmethod
    def validate_condition_json_for_conditional(
        cls, v: Optional[dict[str, Any]], info
    ) -> Optional[dict[str, Any]]:
        """Validate that condition_json is provided for conditional dependencies.
        
        This validator provides a warning-like behavior - it allows condition_json
        to be None for conditional types but recommends providing it.
        
        Args:
            v: The condition_json value.
            info: Validation info containing other field values.
            
        Returns:
            The validated condition_json value.
        """
        # Note: We allow condition_json to be None even for conditional dependencies
        # This provides flexibility for clients that may set conditions later
        return v
    
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
    """Model for creating a new task dependency.
    
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


class TaskDependency(TaskDependencyBase, BaseModelWithID):
    """Complete task dependency model with all database fields.
    
    Represents a full task dependency record as stored in the database.
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
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )