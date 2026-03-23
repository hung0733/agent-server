# pyright: reportMissingImports=false
"""
Pydantic DTOs for agent–tool associations.

Covers two tables:
- agent_type_tools  → AgentTypeToolBase / AgentTypeToolCreate / AgentTypeToolUpdate / AgentTypeTool
- agent_instance_tools → AgentInstanceToolBase / AgentInstanceToolCreate / AgentInstanceToolUpdate / AgentInstanceTool
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    return uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# AgentTypeTool DTOs
# ─────────────────────────────────────────────────────────────────────────────

class AgentTypeToolBase(BaseModel):
    """Shared fields for agent_type_tools records."""

    tool_id: UUID = Field(..., description="ID of the tool")

    is_active: bool = Field(default=True, description="Whether this association is active")

    model_config = ConfigDict(extra="ignore")


class AgentTypeToolCreate(AgentTypeToolBase):
    """DTO for creating a new agent type → tool association."""

    agent_type_id: UUID = Field(..., description="ID of the agent type")


class AgentTypeToolUpdate(BaseModel):
    """DTO for updating an existing agent_type_tools record. Only provided fields are updated."""

    id: UUID = Field(..., description="ID of the record to update")

    is_active: Optional[bool] = Field(default=None, description="New active status")

    model_config = ConfigDict(extra="ignore")


class AgentTypeTool(AgentTypeToolBase):
    """Complete DTO for an agent_type_tools record, as returned from the DAO."""

    id: UUID = Field(default_factory=gen_random_uuid, description="Primary key (UUID v4)")

    agent_type_id: UUID = Field(..., description="ID of the agent type")

    created_at: datetime = Field(default_factory=now_utc, description="Creation timestamp (UTC)")

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440010",
                "agent_type_id": "550e8400-e29b-41d4-a716-446655440000",
                "tool_id": "550e8400-e29b-41d4-a716-446655440001",
                "is_active": True,
                "created_at": "2026-03-23T10:00:00Z",
            }
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# AgentInstanceTool DTOs
# ─────────────────────────────────────────────────────────────────────────────

class AgentInstanceToolBase(BaseModel):
    """Shared fields for agent_instance_tools records."""

    tool_id: UUID = Field(..., description="ID of the tool")

    is_enabled: bool = Field(
        default=True,
        description="False = disable this tool for the instance (overrides type-level grant)",
    )

    config_override: Optional[dict[str, Any]] = Field(
        default=None,
        description="Instance-specific tool configuration overrides (JSONB)",
    )

    model_config = ConfigDict(extra="ignore")


class AgentInstanceToolCreate(AgentInstanceToolBase):
    """DTO for creating a new agent instance → tool override record."""

    agent_instance_id: UUID = Field(..., description="ID of the agent instance")


class AgentInstanceToolUpdate(BaseModel):
    """DTO for updating an existing agent_instance_tools record. Only provided fields are updated."""

    id: UUID = Field(..., description="ID of the record to update")

    is_enabled: Optional[bool] = Field(default=None, description="New enabled status")

    config_override: Optional[dict[str, Any]] = Field(
        default=None, description="New config override"
    )

    model_config = ConfigDict(extra="ignore")


class AgentInstanceTool(AgentInstanceToolBase):
    """Complete DTO for an agent_instance_tools record, as returned from the DAO."""

    id: UUID = Field(default_factory=gen_random_uuid, description="Primary key (UUID v4)")

    agent_instance_id: UUID = Field(..., description="ID of the agent instance")

    created_at: datetime = Field(default_factory=now_utc, description="Creation timestamp (UTC)")

    updated_at: datetime = Field(
        default_factory=now_utc, description="Last update timestamp (UTC)"
    )

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440020",
                "agent_instance_id": "550e8400-e29b-41d4-a716-446655440002",
                "tool_id": "550e8400-e29b-41d4-a716-446655440001",
                "is_enabled": True,
                "config_override": {"timeout_seconds": 30},
                "created_at": "2026-03-23T10:00:00Z",
                "updated_at": "2026-03-23T10:00:00Z",
            }
        },
    )
