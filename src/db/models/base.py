# pyright: reportMissingImports=false
"""
Base models for database entities.

This module provides Pydantic v2 base models with common fields
for database-backed entities.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from db.types import gen_random_uuid


def now_utc() -> datetime:
    """
    Get the current UTC timestamp.
    
    This function is designed to be used as a field default factory
    for datetime fields that need timezone-aware timestamps.
    
    Returns:
        Current UTC datetime with timezone info.
    """
    return datetime.now(timezone.utc)


class BaseModelWithID(BaseModel):
    """
    Base model with standard database fields.
    
    Provides common fields and configuration for all database models:
    - id: UUID identifier, auto-generated
    - created_at: Creation timestamp, auto-set
    - updated_at: Last update timestamp, auto-updated
    
    Usage:
        class MyModel(BaseModelWithID):
            name: str
            value: int
    """

    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)"
    )
    """Primary key - auto-generated UUID v4."""

    created_at: datetime = Field(
        default_factory=now_utc,
        description="Record creation timestamp (UTC)"
    )
    """Timestamp when the record was created (UTC timezone)."""

    updated_at: datetime = Field(
        default_factory=now_utc,
        description="Last update timestamp (UTC)"
    )
    """Timestamp when the record was last updated (UTC timezone)."""

    model_config = {
        "extra": "ignore",
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z"
            }
        }
    }

    def touch(self) -> None:
        """
        Update the updated_at timestamp to current time.
        
        Call this method when modifying the model to track
        when it was last touched.
        """
        self.updated_at = now_utc()
