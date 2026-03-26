# pyright: reportMissingImports=false
"""
Pydantic DTOs for MCP clients.

This module provides Pydantic v2 DTOs for validation and serialization
of MCP client data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.mcp_client_dto
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
# MCP Client DTOs
# =============================================================================

class MCPClientBase(BaseModel):
    """Base model with common MCP client fields."""

    name: str = Field(
        ...,
        min_length=1,
        description="Human-readable name for this MCP client",
    )
    """Client name."""

    description: Optional[str] = Field(
        default=None,
        description="Optional description of the MCP client",
    )
    """Client description."""

    protocol: str = Field(
        ...,
        description="Communication protocol: 'http' or 'websocket'",
    )
    """Protocol type."""

    base_url: str = Field(
        ...,
        description="Base URL of the MCP server",
    )
    """MCP server base URL."""

    api_key_encrypted: Optional[str] = Field(
        default=None,
        description="Encrypted API key for authentication",
    )
    """Encrypted API key."""

    headers: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        description="Custom HTTP headers as JSON",
    )
    """Custom headers."""

    auth_type: Optional[str] = Field(
        default="none",
        description="Authentication type: 'none', 'api_key', 'bearer', 'basic', 'oauth2'",
    )
    """Auth type."""

    auth_config: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        description="Authentication configuration as JSON",
    )
    """Auth configuration."""

    status: str = Field(
        default="disconnected",
        description="Connection status: 'connected', 'disconnected', 'error'",
    )
    """Connection status."""

    last_error: Optional[str] = Field(
        default=None,
        description="Last error message (if any)",
    )
    """Last error."""

    client_metadata: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional metadata as JSON",
    )
    """Client metadata."""

    is_active: bool = Field(
        default=True,
        description="Whether the client is currently active",
    )
    """Active status."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "filesystem-mcp",
                "description": "Filesystem MCP server for file operations",
                "protocol": "http",
                "base_url": "http://localhost:3000",
                "auth_type": "none",
                "status": "disconnected",
                "is_active": True,
            }
        }
    )


class MCPClientCreate(MCPClientBase):
    """DTO for creating a new MCP client.

    Used for input validation when creating MCP clients.
    """

    user_id: UUID = Field(
        ...,
        description="User ID who owns this client",
    )
    """Owner user ID."""


class MCPClientUpdate(BaseModel):
    """DTO for updating an existing MCP client.

    All fields are optional - only provided fields will be updated.
    """

    id: UUID = Field(
        ...,
        description="MCP client ID to update",
    )
    """Client ID."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Client name",
    )

    description: Optional[str] = None
    protocol: Optional[str] = None
    base_url: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    headers: Optional[dict[str, Any]] = None
    auth_type: Optional[str] = None
    auth_config: Optional[dict[str, Any]] = None
    status: Optional[str] = None
    last_connected_at: Optional[datetime] = None
    last_error: Optional[str] = None
    client_metadata: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(extra="ignore")


class MCPClient(MCPClientBase):
    """Complete MCP client DTO with all fields.

    Used for output after database operations.
    Includes generated ID and timestamps.
    """

    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="MCP client UUID",
    )
    """Client ID."""

    user_id: UUID = Field(
        ...,
        description="User ID who owns this client",
    )
    """Owner user ID."""

    last_connected_at: Optional[datetime] = Field(
        default=None,
        description="Last successful connection timestamp",
    )
    """Last connection time."""

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
