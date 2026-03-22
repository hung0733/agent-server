# pyright: reportMissingImports=false
"""
Pydantic models for agent types and agent instances.

This module provides Pydantic v2 models for validation and serialization
of agent type and agent instance data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID, now_utc
from db.types import AgentStatus, gen_random_uuid


class AgentTypeBase(BaseModel):
    """Base model with common agent type fields."""
    
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique name for the agent type",
    )
    """Unique agent type name."""
    
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of the agent type",
    )
    """Agent type description."""
    
    capabilities: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field storing agent capabilities",
    )
    """Agent capabilities as key-value pairs."""
    
    default_config: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field storing default configuration",
    )
    """Default configuration for this agent type."""
    
    is_active: bool = Field(
        default=True,
        description="Whether the agent type is active",
    )
    """Agent type active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "ResearchAgent",
                "description": "An agent that performs web research",
                "capabilities": {"web_search": True, "summarization": True},
                "default_config": {"max_results": 10},
                "is_active": True,
            }
        }
    )


class AgentTypeCreate(AgentTypeBase):
    """Model for creating a new agent type.
    
    Used for input validation when creating agent types.
    """
    
    pass


class AgentType(AgentTypeBase, BaseModelWithID):
    """Complete agent type model with all database fields.
    
    Represents a full agent type record as stored in the database.
    """
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "ResearchAgent",
                "description": "An agent that performs web research",
                "capabilities": {"web_search": True, "summarization": True},
                "default_config": {"max_results": 10},
                "is_active": True,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )


class AgentInstanceBase(BaseModel):
    """Base model with common agent instance fields."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional human-readable name for this instance",
    )
    """Instance name."""
    
    status: AgentStatus = Field(
        default=AgentStatus.idle,
        description="Current operational status",
    )
    """Agent instance status."""
    
    config: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field storing instance-specific configuration",
    )
    """Instance-specific configuration overrides."""
    
    last_heartbeat_at: Optional[datetime] = Field(
        default=None,
        description="Last heartbeat timestamp for liveness detection",
    )
    """Last heartbeat timestamp."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "ResearchAgent-001",
                "status": "idle",
                "config": {"max_results": 20},
                "last_heartbeat_at": "2026-03-22T12:00:00Z",
            }
        }
    )


class AgentInstanceCreate(AgentInstanceBase):
    """Model for creating a new agent instance.
    
    Used for input validation when creating agent instances.
    """
    
    agent_type_id: UUID = Field(
        ...,
        description="ID of the agent type",
    )
    """Foreign key to the agent type."""
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""


class AgentInstance(AgentInstanceBase, BaseModelWithID):
    """Complete agent instance model with all database fields.
    
    Represents a full agent instance record as stored in the database.
    """
    
    agent_type_id: UUID = Field(
        ...,
        description="ID of the agent type",
    )
    """Foreign key to the agent type."""
    
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
                "id": "660f9500-f39c-51e5-b827-557766550001",
                "agent_type_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "name": "ResearchAgent-001",
                "status": "idle",
                "config": {"max_results": 20},
                "last_heartbeat_at": "2026-03-22T12:00:00Z",
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )
