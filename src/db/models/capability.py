# pyright: reportMissingImports=false
"""
Pydantic models for agent capabilities.

This module provides Pydantic v2 models for validation and serialization
of agent capability data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID
from db.types import gen_random_uuid


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
    """Model for creating a new agent capability.
    
    Used for input validation when creating capabilities.
    """
    
    agent_type_id: UUID = Field(
        ...,
        description="ID of the agent type",
    )
    """Foreign key to the agent type."""


class AgentCapability(AgentCapabilityBase, BaseModelWithID):
    """Complete agent capability model with all database fields.
    
    Represents a full capability record as stored in the database.
    """
    
    agent_type_id: UUID = Field(
        ...,
        description="ID of the agent type",
    )
    """Foreign key to the agent type."""
    
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
