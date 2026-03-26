# pyright: reportMissingImports=false
"""
Pydantic DTOs for MCP tools.

This module provides Pydantic v2 DTOs for validation and serialization
of MCP tool data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.mcp_tool_dto
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
# MCP Tool DTOs
# =============================================================================

class MCPToolBase(BaseModel):
    """Base model with common MCP tool fields."""

    mcp_tool_name: str = Field(
        ...,
        min_length=1,
        description="Original tool name from MCP server",
    )
    """MCP tool name."""

    mcp_tool_description: Optional[str] = Field(
        default=None,
        description="Tool description from MCP server",
    )
    """Tool description."""

    mcp_tool_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool input schema from MCP server (JSON Schema format)",
    )
    """Tool schema."""

    is_active: bool = Field(
        default=True,
        description="Whether this tool mapping is currently active",
    )
    """Active status."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "mcp_tool_name": "read_file",
                "mcp_tool_description": "Read contents of a file",
                "is_active": True,
            }
        }
    )


class MCPToolCreate(MCPToolBase):
    """DTO for creating a new MCP tool mapping.

    Used for input validation when creating MCP tool mappings.
    """

    mcp_client_id: UUID = Field(
        ...,
        description="MCP client ID providing this tool",
    )
    """MCP client ID."""

    tool_id: UUID = Field(
        ...,
        description="Internal tool ID",
    )
    """Tool ID."""


class MCPToolUpdate(BaseModel):
    """DTO for updating an existing MCP tool.

    All fields are optional - only provided fields will be updated.
    """

    id: UUID = Field(
        ...,
        description="MCP tool ID to update",
    )
    """MCP tool ID."""

    mcp_tool_name: Optional[str] = Field(
        default=None,
        min_length=1,
    )
    mcp_tool_description: Optional[str] = None
    mcp_tool_schema: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    last_invoked_at: Optional[datetime] = None
    invocation_count: Optional[int] = None

    model_config = ConfigDict(extra="ignore")


class MCPTool(MCPToolBase):
    """Complete MCP tool DTO with all fields.

    Used for output after database operations.
    Includes generated ID and timestamps.
    """

    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="MCP tool UUID",
    )
    """MCP tool ID."""

    mcp_client_id: UUID = Field(
        ...,
        description="MCP client ID providing this tool",
    )
    """MCP client ID."""

    tool_id: UUID = Field(
        ...,
        description="Internal tool ID",
    )
    """Tool ID."""

    last_invoked_at: Optional[datetime] = Field(
        default=None,
        description="Last invocation timestamp",
    )
    """Last invocation time."""

    invocation_count: int = Field(
        default=0,
        description="Total number of invocations",
    )
    """Invocation count."""

    created_at: datetime = Field(
        default_factory=now_utc,
        description="Record creation timestamp (UTC)",
    )
    """Creation timestamp."""

    updated_at: datetime = Field(
        default_factory=now_utc,
        description="Last update timestamp (UTC)",
    )
    """Update timestamp."""

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,  # Enable ORM mode for SQLAlchemy integration
    )
