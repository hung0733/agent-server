# pyright: reportMissingImports=false
"""
Base Pydantic DTO for data transfer objects.

This module provides the base model class and utility functions
for all DTOs in the db.dto layer.

Import path: db.dto.base
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


def now_utc() -> datetime:
    """Get current UTC datetime.
    
    Returns:
        datetime: Current datetime with UTC timezone.
    """
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4.
    
    Returns:
        UUID: A new random UUID version 4.
    """
    return uuid4()


class BaseModelWithID(BaseModel):
    """Base model with common ID and timestamp fields.
    
    This base class provides:
    - id: UUID primary key (auto-generated)
    - created_at: Creation timestamp (auto-generated, UTC)
    - updated_at: Last update timestamp (auto-generated, UTC)
    
    Example:
        class User(BaseModelWithID):
            username: str
            email: str
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
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
    )
    
    def touch(self) -> None:
        """Update the updated_at timestamp to current time.
        
        Call this method when modifying the model to ensure
        the updated_at field reflects the modification time.
        """
        self.updated_at = now_utc()