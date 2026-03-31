# pyright: reportMissingImports=false
"""
Pydantic DTOs for agent types and agent instances.

This module provides Pydantic v2 DTOs for validation and serialization
of agent type and agent instance data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.agent_dto
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


# =============================================================================
# AgentType DTOs
# =============================================================================

class AgentTypeBase(BaseModel):
    """Base model with common agent type fields."""

    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Owning user ID."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name for the agent type (unique per user)",
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
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "name": "ResearchAgent",
                "description": "An agent that performs web research",
                "capabilities": {"web_search": True, "summarization": True},
                "default_config": {"max_results": 10},
                "is_active": True,
            }
        }
    )


class AgentTypeCreate(AgentTypeBase):
    """DTO for creating a new agent type.
    
    Used for input validation when creating agent types.
    """
    
    pass


class AgentTypeUpdate(BaseModel):
    """DTO for updating an existing agent type.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the agent type to update",
    )
    """ID of agent type to update (required)."""
    
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New name for the agent type",
    )
    """New name (optional)."""
    
    description: Optional[str] = Field(
        default=None,
        description="New description",
    )
    """New description (optional)."""
    
    capabilities: Optional[dict[str, Any]] = Field(
        default=None,
        description="New capabilities",
    )
    """New capabilities (optional)."""
    
    default_config: Optional[dict[str, Any]] = Field(
        default=None,
        description="New default configuration",
    )
    """New default config (optional)."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="New active status",
    )
    """New active status (optional)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class AgentType(AgentTypeBase):
    """Complete agent type DTO with all database fields.
    
    Represents a full agent type record as stored in the database.
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
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
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


# =============================================================================
# AgentInstance DTOs
# =============================================================================

class AgentInstanceBase(BaseModel):
    """Base model with common agent instance fields."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional human-readable name for this instance",
    )
    """Instance name."""
    
    status: str = Field(
        default="idle",
        description="Current operational status (idle, busy, error, offline)",
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

    agent_id: Optional[str] = Field(
        default=None,
        description="Unique string identifier for this agent instance",
    )
    """Unique string agent identifier (e.g. 'butler-001')."""

    endpoint_group_id: Optional[UUID] = Field(
        default=None,
        description="ID of the LLM endpoint group assigned to this instance",
    )
    """FK to llm_endpoint_groups."""

    phone_no: Optional[str] = Field(
        default=None,
        description="Phone number associated with this agent instance",
    )
    """Agent phone number."""

    whatsapp_key: Optional[str] = Field(
        default=None,
        description="WhatsApp authentication key for this agent instance",
    )
    """WhatsApp key."""

    is_sub_agent: bool = Field(
        default=False,
        description="Whether this agent instance is a sub-agent",
    )
    """Sub-agent marker flag."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "ResearchAgent-001",
                "status": "idle",
                "config": {"max_results": 20},
                "last_heartbeat_at": "2026-03-22T12:00:00Z",
                "agent_id": "butler-001",
                "endpoint_group_id": None,
                "phone_no": None,
                "whatsapp_key": None,
                "is_sub_agent": False,
            }
        }
    )


class AgentInstanceCreate(AgentInstanceBase):
    """DTO for creating a new agent instance.
    
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


class AgentInstanceUpdate(BaseModel):
    """DTO for updating an existing agent instance.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the agent instance to update",
    )
    """ID of agent instance to update (required)."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="New name for the instance",
    )
    """New name (optional)."""
    
    status: Optional[str] = Field(
        default=None,
        description="New status",
    )
    """New status (optional)."""
    
    config: Optional[dict[str, Any]] = Field(
        default=None,
        description="New configuration",
    )
    """New config (optional)."""
    
    last_heartbeat_at: Optional[datetime] = Field(
        default=None,
        description="New heartbeat timestamp",
    )
    """New heartbeat timestamp (optional)."""

    agent_id: Optional[str] = Field(
        default=None,
        description="New unique string identifier for this agent instance",
    )
    """New agent_id (optional)."""

    endpoint_group_id: Optional[UUID] = Field(
        default=None,
        description="New LLM endpoint group ID",
    )
    """New endpoint group FK (optional)."""

    phone_no: Optional[str] = Field(
        default=None,
        description="New phone number",
    )
    """New phone number (optional)."""

    whatsapp_key: Optional[str] = Field(
        default=None,
        description="New WhatsApp key",
    )
    """New WhatsApp key (optional)."""

    is_sub_agent: Optional[bool] = Field(
        default=None,
        description="New sub-agent flag",
    )
    """New sub-agent marker (optional)."""

    model_config = ConfigDict(
        extra="ignore",
    )


class AgentInstance(AgentInstanceBase):
    """Complete agent instance DTO with all database fields.
    
    Represents a full agent instance record as stored in the database.
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
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
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
                "id": "660f9500-f39c-51e5-b827-557766550001",
                "agent_type_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "name": "ResearchAgent-001",
                "status": "idle",
                "config": {"max_results": 20},
                "last_heartbeat_at": "2026-03-22T12:00:00Z",
                "is_sub_agent": False,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )
