# pyright: reportMissingImports=false
"""
Pydantic DTOs for tools and tool versions.

This module provides Pydantic v2 DTOs for validation and serialization
of tool and tool version data. Follows the Base/Create/Update/Complete pattern.

Import path: src.db.dto.tool_dto
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
# Tool DTOs
# =============================================================================

class ToolBase(BaseModel):
    """Base model with common tool fields."""
    
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique tool name for identification",
    )
    """Unique tool name."""
    
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of the tool",
    )
    """Tool description."""
    
    is_active: bool = Field(
        default=True,
        description="Whether the tool is currently active/available",
    )
    """Tool active status."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "web_search",
                "description": "Search the web for information",
                "is_active": True,
            }
        }
    )


class ToolCreate(ToolBase):
    """DTO for creating a new tool.
    
    Used for input validation when creating tools.
    """
    
    pass


class ToolUpdate(BaseModel):
    """DTO for updating an existing tool.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the tool to update",
    )
    """ID of tool to update (required)."""
    
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New tool name",
    )
    """New tool name (optional)."""
    
    description: Optional[str] = Field(
        default=None,
        description="New description",
    )
    """New description (optional)."""
    
    is_active: Optional[bool] = Field(
        default=None,
        description="New active status",
    )
    """New active status (optional)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class Tool(ToolBase):
    """Complete tool DTO with all database fields.
    
    Represents a full tool record as stored in the database.
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
                "name": "web_search",
                "description": "Search the web for information",
                "is_active": True,
                "created_at": "2026-03-22T12:00:00Z",
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )


# =============================================================================
# ToolVersion DTOs
# =============================================================================

class ToolVersionBase(BaseModel):
    """Base model with common tool version fields."""
    
    version: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Version string (e.g., '1.0.0', '2.1.3')",
    )
    """Version string."""
    
    input_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema for validating tool inputs",
    )
    """Input validation schema."""
    
    output_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema for validating tool outputs",
    )
    """Output validation schema."""
    
    implementation_ref: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Reference to implementation (e.g., module.path:function_name)",
    )
    """Implementation reference."""
    
    config_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool-specific configuration as JSON",
    )
    """Tool configuration."""
    
    is_default: bool = Field(
        default=False,
        description="Whether this is the default version for the tool",
    )
    """Default version flag."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "version": "1.0.0",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "results": {"type": "array", "items": {"type": "object"}}
                    },
                },
                "implementation_ref": "tools.web_search:search",
                "config_json": {"timeout": 30, "max_results": 10},
                "is_default": True,
            }
        }
    )


class ToolVersionCreate(ToolVersionBase):
    """DTO for creating a new tool version.
    
    Used for input validation when creating tool versions.
    """
    
    tool_id: UUID = Field(
        ...,
        description="ID of the parent tool",
    )
    """Foreign key to the parent tool."""


class ToolVersionUpdate(BaseModel):
    """DTO for updating an existing tool version.
    
    All fields are optional - only provided fields will be updated.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the tool version to update",
    )
    """ID of tool version to update (required)."""
    
    version: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="New version string",
    )
    """New version string (optional)."""
    
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
    
    implementation_ref: Optional[str] = Field(
        default=None,
        max_length=500,
        description="New implementation reference",
    )
    """New implementation reference (optional)."""
    
    config_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="New configuration",
    )
    """New configuration (optional)."""
    
    is_default: Optional[bool] = Field(
        default=None,
        description="New default flag",
    )
    """New default flag (optional)."""
    
    model_config = ConfigDict(
        extra="ignore",
    )


class ToolVersion(ToolVersionBase):
    """Complete tool version DTO with all database fields.
    
    Represents a full tool version record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
    tool_id: UUID = Field(
        ...,
        description="ID of the parent tool",
    )
    """Foreign key to the parent tool."""
    
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
                "tool_id": "550e8400-e29b-41d4-a716-446655440000",
                "version": "1.0.0",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "results": {"type": "array", "items": {"type": "object"}}
                    },
                },
                "implementation_ref": "tools.web_search:search",
                "config_json": {"timeout": 30, "max_results": 10},
                "is_default": True,
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )