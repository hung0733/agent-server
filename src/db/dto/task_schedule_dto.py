# pyright: reportMissingImports=false
"""
Pydantic DTOs for task schedules.

This module provides Pydantic v2 DTOs for validation and serialization
of task schedule data with schedule expression validation.
Follows the Base/Create/Update/Complete pattern.

Import path: db.dto.task_schedule_dto
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.types import ScheduleType


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


# Cron expression validation regex
# Matches 5 space-separated parts: minute hour day month weekday
# Each part can be: *, numbers, ranges (1-5), lists (1,2,3), or steps (*/5)
CRON_PATTERN = re.compile(
    r'^(\*|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*|\*/[0-9]+)( +(\*|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*|\*/[0-9]+)){4}$'
)

# ISO 8601 duration validation regex
# Matches: P[n]Y[n]M[n]DT[n]H[n]M[n]S or P[n]W
ISO8601_DURATION_PATTERN = re.compile(
    r'^P(\d+Y)?(\d+M)?(\d+D)?(T(\d+H)?(\d+M)?(\d+S)?)?$|^P\d+W$'
)

# ISO 8601 timestamp validation regex
# Matches: YYYY-MM-DDTHH:MM:SS[.ms][Z|+HH:MM|-HH:MM]
ISO8601_TIMESTAMP_PATTERN = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$'
)


def validate_cron_expression(expr: str) -> str:
    """Validate cron expression format.
    
    Args:
        expr: Cron expression to validate (5 space-separated parts)
        
    Returns:
        The validated expression
        
    Raises:
        ValueError: If expression doesn't match cron format
    """
    if not CRON_PATTERN.match(expr):
        raise ValueError(
            f"Invalid cron expression: {expr!r}. "
            "Expected 5 space-separated parts (minute hour day month weekday). "
            "Each part can be *, numbers, ranges (1-5), lists (1,2,3), or steps (*/5)."
        )
    return expr


def validate_interval_expression(expr: str) -> str:
    """Validate ISO 8601 duration format.
    
    Args:
        expr: Duration expression to validate
        
    Returns:
        The validated expression
        
    Raises:
        ValueError: If expression doesn't match ISO 8601 duration format
    """
    if not ISO8601_DURATION_PATTERN.match(expr):
        raise ValueError(
            f"Invalid interval expression: {expr!r}. "
            "Expected ISO 8601 duration format (e.g., PT1H for hourly, P1D for daily, P1W for weekly)."
        )
    return expr


def validate_once_expression(expr: str) -> str:
    """Validate ISO 8601 timestamp format.
    
    Args:
        expr: Timestamp expression to validate
        
    Returns:
        The validated expression
        
    Raises:
        ValueError: If expression doesn't match ISO 8601 timestamp format
    """
    if not ISO8601_TIMESTAMP_PATTERN.match(expr):
        raise ValueError(
            f"Invalid once expression: {expr!r}. "
            "Expected ISO 8601 timestamp format (e.g., 2026-03-22T12:00:00Z)."
        )
    return expr


# =============================================================================
# TaskSchedule DTOs
# =============================================================================

class TaskScheduleBase(BaseModel):
    """Base model with common task schedule fields."""
    
    schedule_type: ScheduleType = Field(
        default=ScheduleType.cron,
        description="Type of schedule: once, interval, or cron",
    )
    """Schedule type determines expression format."""
    
    schedule_expression: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Schedule expression (format depends on schedule_type)",
    )
    """Schedule expression - format validated based on schedule_type."""
    
    is_active: bool = Field(
        default=True,
        description="Whether the schedule is active and should be processed",
    )
    """Schedule active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "schedule_type": "cron",
                "schedule_expression": "0 12 * * *",
                "is_active": True,
            }
        }
    )


class TaskScheduleCreate(TaskScheduleBase):
    """DTO for creating a new task schedule.
    
    Used for input validation when creating schedules.
    """
    
    task_template_id: UUID = Field(
        ...,
        description="ID of the task template to schedule",
    )
    """Foreign key to the task template."""
    
    next_run_at: Optional[datetime] = Field(
        default=None,
        description="Next scheduled execution time",
    )
    """Next run time (set by scheduler service)."""
    
    last_run_at: Optional[datetime] = Field(
        default=None,
        description="Last execution timestamp",
    )
    """Last run time."""

    consecutive_failures: int = Field(
        default=0,
        ge=0,
        description="Number of consecutive execution failures",
    )
    """Consecutive failure count (reset to 0 on success)."""

    last_failure_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last execution failure",
    )
    """Last failure timestamp (NULL if never failed or last run succeeded)."""

    @model_validator(mode="after")
    def validate_expression_format(self) -> "TaskScheduleCreate":
        """Validate schedule_expression format based on schedule_type."""
        if self.schedule_type == ScheduleType.cron:
            validate_cron_expression(self.schedule_expression)
        elif self.schedule_type == ScheduleType.interval:
            validate_interval_expression(self.schedule_expression)
        elif self.schedule_type == ScheduleType.once:
            validate_once_expression(self.schedule_expression)
        return self
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "task_template_id": "550e8400-e29b-41d4-a716-446655440000",
                "schedule_type": "cron",
                "schedule_expression": "0 12 * * *",
                "is_active": True,
            }
        }
    )


class TaskScheduleUpdate(BaseModel):
    """DTO for updating an existing task schedule.
    
    All fields are optional to allow partial updates.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the task schedule to update",
    )
    """ID of task schedule to update (required)."""
    
    schedule_type: Optional[ScheduleType] = Field(
        default=None,
        description="Type of schedule",
    )
    """Schedule type."""
    
    schedule_expression: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Schedule expression",
    )
    """Schedule expression."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether the schedule is active",
    )
    """Active status."""
    
    next_run_at: Optional[datetime] = Field(
        default=None,
        description="Next scheduled execution time",
    )
    """Next run time (set by scheduler service)."""
    
    last_run_at: Optional[datetime] = Field(
        default=None,
        description="Last execution timestamp",
    )
    """Last run time."""

    consecutive_failures: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of consecutive execution failures",
    )
    """Consecutive failure count (reset to 0 on success)."""

    last_failure_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last execution failure",
    )
    """Last failure timestamp (NULL if never failed or last run succeeded)."""

    @model_validator(mode="after")
    def validate_expression_if_provided(self) -> "TaskScheduleUpdate":
        """Validate schedule_expression format if provided."""
        if self.schedule_expression is not None and self.schedule_type is not None:
            if self.schedule_type == ScheduleType.cron:
                validate_cron_expression(self.schedule_expression)
            elif self.schedule_type == ScheduleType.interval:
                validate_interval_expression(self.schedule_expression)
            elif self.schedule_type == ScheduleType.once:
                validate_once_expression(self.schedule_expression)
        return self
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "is_active": False,
                "next_run_at": "2026-03-22T12:00:00Z",
            }
        }
    )


class TaskSchedule(TaskScheduleBase):
    """Complete task schedule DTO with all database fields.
    
    Represents a full schedule record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
    task_template_id: UUID = Field(
        ...,
        description="ID of the task template to schedule",
    )
    """Foreign key to the task template."""
    
    next_run_at: Optional[datetime] = Field(
        default=None,
        description="Next scheduled execution time (computed by background job)",
    )
    """Next run time."""
    
    last_run_at: Optional[datetime] = Field(
        default=None,
        description="Last execution timestamp",
    )
    """Last run time."""
    
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

    consecutive_failures: int = Field(
        default=0,
        ge=0,
        description="Number of consecutive execution failures",
    )
    """Consecutive failure count (reset to 0 on success)."""

    last_failure_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last execution failure",
    )
    """Last failure timestamp (NULL if never failed or last run succeeded)."""

    @model_validator(mode="after")
    def validate_expression_format(self) -> "TaskSchedule":
        """Validate schedule_expression format based on schedule_type."""
        if self.schedule_type == ScheduleType.cron:
            validate_cron_expression(self.schedule_expression)
        elif self.schedule_type == ScheduleType.interval:
            validate_interval_expression(self.schedule_expression)
        elif self.schedule_type == ScheduleType.once:
            validate_once_expression(self.schedule_expression)
        return self
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "task_template_id": "550e8400-e29b-41d4-a716-446655440000",
                "schedule_type": "cron",
                "schedule_expression": "0 12 * * *",
                "next_run_at": "2026-03-22T12:00:00Z",
                "last_run_at": "2026-03-22T11:00:00Z",
                "is_active": True,
                "created_at": "2026-03-22T10:00:00Z",
                "updated_at": "2026-03-22T11:00:00Z",
            }
        }
    )