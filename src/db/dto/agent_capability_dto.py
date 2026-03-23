# pyright: reportMissingImports=false
"""
Pydantic DTOs for agent capabilities.

This module provides Pydantic v2 DTOs for validation and serialization
of agent capability data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.agent_capability_dto
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


class AgentCapabilityBase(BaseModel):
    """Base model with common capability fields."""
    
    capability_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the capability",
    )
    """Capability name."""
    
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Human-readable description of the capability",
    )
    """Capability description."""
    
    input_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema definition for input validation",
    )
    """JSON Schema for validating capability inputs."""
    
    output_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema definition for output validation",
    )
    """JSON Schema for validating capability outputs."""
    
    is_active: bool = Field(
        default=True,
        description="Whether the capability is active",
    )
    """Capability active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "capability_name": "web_search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "results": {"type": "array", "items": {"type": "object"}}
                    }
                },
                "is_active": True,
            }
        }
    )


class AgentCapabilityCreate(AgentCapabilityBase):
    """DTO for creating a new agent capability.
    
    Used for input validation when creating capabilities.
    """
    
    agent_type_id: UUID = Field(
        ...,
        description="ID of the agent type",
    )
    """Foreign key to the agent type."""


class AgentCapabilityUpdate(BaseModel):
    """DTO for updating an existing agent capability.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the capability to update",
    )
    """ID of capability to update (required)."""
    
    capability_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New capability name",
    )
    """New capability name (optional)."""
    
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="New description",
    )
    """New description (optional)."""
    
    input_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="New input schema",
    )
    """New input schema (optional)."""
    
    output_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="New output schema",
    )
    """New output schema (optional)."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="New active status",
    )
    """New active status (optional)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class AgentCapability(AgentCapabilityBase):
    """Complete agent capability DTO with all database fields.
    
    Represents a full capability record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
    agent_type_id: UUID = Field(
        ...,
        description="ID of the agent type",
    )
    """Foreign key to the agent type."""
    
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
                "agent_type_id": "550e8400-e29b-41d4-a716-446655440000",
                "capability_name": "web_search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "results": {"type": "array", "items": {"type": "object"}}
                    }
                },
                "is_active": True,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )