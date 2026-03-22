# pyright: reportMissingImports=false
"""
Pydantic models for users and API keys.

This module provides Pydantic v2 models for validation and serialization
of user and API key data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from db.models.base import BaseModelWithID, now_utc
from db.types import gen_random_uuid


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
    """Model for creating a new user.
    
    Used for input validation when creating users.
    """
    
    pass


class User(UserBase, BaseModelWithID):
    """Complete user model with all database fields.
    
    Represents a full user record as stored in the database.
    """
    
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
    """Model for creating a new API key.
    
    Used for input validation when creating API keys.
    Note: key_hash should be generated from the plain text API key
    before creating the record - never accept plain text keys.
    """
    
    key_hash: str = Field(
        ...,
        description="Hashed API key value",
    )
    """Hashed API key - never store plain text."""


class APIKey(APIKeyBase, BaseModelWithID):
    """Complete API key model with all database fields.
    
    Represents a full API key record as stored in the database.
    """
    
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
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )
