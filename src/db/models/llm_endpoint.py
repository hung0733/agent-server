# pyright: reportMissingImports=false
"""
Pydantic models for LLM endpoint groups, endpoints, and level endpoints.

This module provides Pydantic v2 models for validation and serialization
of LLM endpoint group, endpoint, and level endpoint data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db.models.base import BaseModelWithID, now_utc
from db.types import gen_random_uuid


# =============================================================================
# LLM Endpoint Group Models
# =============================================================================

class LLMEndpointGroupBase(BaseModel):
    """Base model with common LLM endpoint group fields."""
    
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the endpoint group",
    )
    """Endpoint group name."""
    
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional description of the endpoint group",
    )
    """Endpoint group description."""
    
    is_default: bool = Field(
        default=False,
        description="Whether this is the user's default endpoint group",
    )
    """Default endpoint group flag (only one per user)."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "Production LLMs",
                "description": "Production LLM endpoints for high-availability",
                "is_default": True,
            }
        }
    )


class LLMEndpointGroupCreate(LLMEndpointGroupBase):
    """Model for creating a new LLM endpoint group.
    
    Used for input validation when creating endpoint groups.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""


class LLMEndpointGroup(LLMEndpointGroupBase, BaseModelWithID):
    """Complete LLM endpoint group model with all database fields.
    
    Represents a full LLM endpoint group record as stored in the database.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "name": "Production LLMs",
                "description": "Production LLM endpoints for high-availability",
                "is_default": True,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )


# =============================================================================
# LLM Endpoint Models
# =============================================================================

class LLMEndpointBase(BaseModel):
    """Base model with common LLM endpoint fields."""
    
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable name for this endpoint configuration",
    )
    """Endpoint name."""
    
    base_url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Base URL for the LLM API endpoint",
    )
    """Base URL for the API (e.g., 'https://api.openai.com/v1')."""
    
    api_key: str = Field(
        ...,
        min_length=1,
        description="API key for authentication (will be encrypted on storage)",
    )
    """API key for authentication. Encrypted before storage."""
    
    model_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the model to use",
    )
    """Model name (e.g., 'gpt-4', 'claude-3-opus')."""
    
    config_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for advanced configuration settings",
    )
    """Advanced configuration (temperature, max_tokens, etc.)."""
    
    is_active: bool = Field(
        default=True,
        description="Whether this endpoint is currently active",
    )
    """Active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "OpenAI GPT-4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-...",
                "model_name": "gpt-4",
                "config_json": {"temperature": 0.7, "max_tokens": 4096},
                "is_active": True,
            }
        }
    )


class LLMEndpointCreate(LLMEndpointBase):
    """Model for creating a new LLM endpoint.
    
    Used for input validation when creating endpoints.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""


class LLMEndpointUpdate(BaseModel):
    """Model for updating an existing LLM endpoint.
    
    All fields are optional to allow partial updates.
    """
    
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Human-readable name for this endpoint configuration",
    )
    """Endpoint name."""
    
    base_url: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Base URL for the LLM API endpoint",
    )
    """Base URL for the API."""
    
    api_key: Optional[str] = Field(
        default=None,
        min_length=1,
        description="API key for authentication (will be encrypted on storage)",
    )
    """API key for authentication. Encrypted before storage."""
    
    model_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Name of the model to use",
    )
    """Model name."""
    
    config_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for advanced configuration settings",
    )
    """Advanced configuration."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether this endpoint is currently active",
    )
    """Active status."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class LLMEndpoint(BaseModelWithID):
    """Complete LLM endpoint model with all database fields.
    
    Represents a full LLM endpoint record as stored in the database.
    Note: api_key_encrypted field is excluded from serialization by default
    for security reasons.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
    name: str = Field(
        ...,
        description="Human-readable name for this endpoint configuration",
    )
    """Endpoint name."""
    
    base_url: str = Field(
        ...,
        description="Base URL for the LLM API endpoint",
    )
    """Base URL for the API."""
    
    model_name: str = Field(
        ...,
        description="Name of the model to use",
    )
    """Model name."""
    
    config_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field for advanced configuration settings",
    )
    """Advanced configuration."""
    
    is_active: bool = Field(
        default=True,
        description="Whether this endpoint is currently active",
    )
    """Active status."""
    
    last_success_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last successful API call",
    )
    """Last success timestamp."""
    
    last_failure_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last failed API call",
    )
    """Last failure timestamp."""
    
    failure_count: int = Field(
        default=0,
        ge=0,
        description="Count of consecutive failures",
    )
    """Consecutive failure count."""
    
    # Note: We don't expose api_key_encrypted in the Pydantic model
    # for security reasons. The encrypted key should only be accessed
    # through the SQLAlchemy model and decrypted when needed.
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "660f9500-f39c-51e5-b827-557766550001",
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "name": "OpenAI GPT-4",
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-4",
                "config_json": {"temperature": 0.7, "max_tokens": 4096},
                "is_active": True,
                "last_success_at": "2026-03-22T12:00:00Z",
                "last_failure_at": None,
                "failure_count": 0,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )


# =============================================================================
# LLM Level Endpoint Models
# =============================================================================

class LLMLevelEndpointBase(BaseModel):
    """Base model with common LLM level endpoint fields."""
    
    difficulty_level: int = Field(
        ...,
        ge=1,
        le=3,
        description="Difficulty level: 1 (simple), 2 (medium), or 3 (complex)",
    )
    """Difficulty level (1-3)."""
    
    involves_secrets: bool = Field(
        default=False,
        description="Whether this endpoint assignment involves handling secrets/sensitive data",
    )
    """Secrets involvement flag."""
    
    priority: int = Field(
        default=0,
        ge=0,
        description="Priority for endpoint selection (higher = preferred)",
    )
    """Selection priority."""
    
    is_active: bool = Field(
        default=True,
        description="Whether this level endpoint assignment is active",
    )
    """Active status."""
    
    @field_validator('difficulty_level')
    @classmethod
    def validate_difficulty_level(cls, v: int) -> int:
        """Validate difficulty level is between 1 and 3."""
        if v < 1 or v > 3:
            raise ValueError('difficulty_level must be between 1 and 3')
        return v
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "difficulty_level": 2,
                "involves_secrets": False,
                "priority": 10,
                "is_active": True,
            }
        }
    )


class LLMLevelEndpointCreate(LLMLevelEndpointBase):
    """Model for creating a new LLM level endpoint.
    
    Used for input validation when creating level endpoint assignments.
    """
    
    group_id: UUID = Field(
        ...,
        description="ID of the endpoint group",
    )
    """Foreign key to the endpoint group."""
    
    endpoint_id: UUID = Field(
        ...,
        description="ID of the LLM endpoint",
    )
    """Foreign key to the LLM endpoint."""


class LLMLevelEndpointUpdate(BaseModel):
    """Model for updating an existing LLM level endpoint.
    
    All fields are optional to allow partial updates.
    """
    
    difficulty_level: Optional[int] = Field(
        default=None,
        ge=1,
        le=3,
        description="Difficulty level: 1 (simple), 2 (medium), or 3 (complex)",
    )
    """Difficulty level (1-3)."""
    
    involves_secrets: Optional[bool] = Field(
        default=None,
        description="Whether this endpoint assignment involves handling secrets/sensitive data",
    )
    """Secrets involvement flag."""
    
    priority: Optional[int] = Field(
        default=None,
        ge=0,
        description="Priority for endpoint selection (higher = preferred)",
    )
    """Selection priority."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether this level endpoint assignment is active",
    )
    """Active status."""
    
    @field_validator('difficulty_level')
    @classmethod
    def validate_difficulty_level(cls, v: Optional[int]) -> Optional[int]:
        """Validate difficulty level is between 1 and 3 if provided."""
        if v is not None and (v < 1 or v > 3):
            raise ValueError('difficulty_level must be between 1 and 3')
        return v
    
    model_config = ConfigDict(
        extra="ignore",
    )


class LLMLevelEndpoint(LLMLevelEndpointBase, BaseModelWithID):
    """Complete LLM level endpoint model with all database fields.
    
    Represents a full LLM level endpoint record as stored in the database.
    """
    
    group_id: UUID = Field(
        ...,
        description="ID of the endpoint group",
    )
    """Foreign key to the endpoint group."""
    
    endpoint_id: UUID = Field(
        ...,
        description="ID of the LLM endpoint",
    )
    """Foreign key to the LLM endpoint."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "770fa600-g40d-62f6-c938-668877660002",
                "group_id": "550e8400-e29b-41d4-a716-446655440000",
                "difficulty_level": 2,
                "involves_secrets": False,
                "endpoint_id": "660f9500-f39c-51e5-b827-557766550001",
                "priority": 10,
                "is_active": True,
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )