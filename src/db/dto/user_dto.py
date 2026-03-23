# pyright: reportMissingImports=false
"""
Pydantic DTOs for users and API keys.

This module provides Pydantic v2 DTOs for validation and serialization
of user and API key data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.user_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


# =============================================================================
# User DTOs
# =============================================================================

class UserBase(BaseModel):
    """Base model with common user fields."""
    
    username: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique username for login and identification",
    )
    """Unique username."""
    
    email: str = Field(
        ...,
        description="Unique email address",
    )
    """User email address."""
    
    is_active: bool = Field(
        default=True,
        description="Whether the user account is active",
    )
    """Account active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "username": "johndoe",
                "email": "john@example.com",
                "is_active": True,
            }
        }
    )


class UserCreate(UserBase):
    """DTO for creating a new user.
    
    Used for input validation when creating users.
    """
    
    pass


class UserUpdate(BaseModel):
    """DTO for updating an existing user.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the user to update",
    )
    """ID of user to update (required)."""
    
    username: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New username",
    )
    """New username (optional)."""
    
    email: Optional[str] = Field(
        default=None,
        description="New email address",
    )
    """New email address (optional)."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="New active status",
    )
    """New active status (optional)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class User(UserBase):
    """Complete user DTO with all database fields.
    
    Represents a full user record as stored in the database.
    Used as the return type from DAO methods.
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
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "username": "johndoe",
                "email": "john@example.com",
                "is_active": True,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )


# =============================================================================
# API Key DTOs
# =============================================================================

class APIKeyBase(BaseModel):
    """Base model with common API key fields."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional human-readable name for the key",
    )
    """Human-readable key name."""
    
    is_active: bool = Field(
        default=True,
        description="Whether the API key is active",
    )
    """Key active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "Production API Key",
                "is_active": True,
            }
        }
    )


class APIKeyCreate(APIKeyBase):
    """DTO for creating a new API key.
    
    Used for input validation when creating API keys.
    Note: key_hash should be generated from the plain text API key
    before creating the record - never accept plain text keys.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user (required)."""
    
    key_hash: str = Field(
        ...,
        description="Hashed API key value",
    )
    """Hashed API key - never store plain text."""
    
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Last time this key was used",
    )
    """Last usage timestamp."""
    
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional expiration timestamp",
    )
    """Key expiration timestamp."""


class APIKeyUpdate(BaseModel):
    """DTO for updating an existing API key.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the API key to update",
    )
    """ID of API key to update (required)."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="New name for the key",
    )
    """New name (optional)."""
    
    key_hash: Optional[str] = Field(
        default=None,
        description="New hashed key value",
    )
    """New key hash (optional)."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="New active status",
    )
    """New active status (optional)."""
    
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Last usage timestamp",
    )
    """Last usage timestamp (optional)."""
    
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Expiration timestamp",
    )
    """Expiration timestamp (optional)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class APIKey(APIKeyBase):
    """Complete API key DTO with all database fields.
    
    Represents a full API key record as stored in the database.
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
    
    key_hash: str = Field(
        ...,
        description="Hashed API key value",
    )
    """Hashed API key value."""
    
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Last time this key was used",
    )
    """Last usage timestamp."""
    
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional expiration timestamp",
    )
    """Key expiration timestamp."""
    
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
                "id": "660f9500-f39c-51e5-b827-557766550001",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "key_hash": "sha256:abc123...",
                "name": "Production API Key",
                "last_used_at": "2026-03-22T12:00:00Z",
                "expires_at": None,
                "is_active": True,
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )