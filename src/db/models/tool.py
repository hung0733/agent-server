# pyright: reportMissingImports=false
"""
Pydantic models for tools and tool versions.

This module provides Pydantic v2 models for validation and serialization
of tool and tool version data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from db.models.base import BaseModelWithID
from db.types import gen_random_uuid


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
    """Model for creating a new tool.

    Used for input validation when creating tools.
    """

    pass


class Tool(ToolBase, BaseModelWithID):
    """Complete tool model with all database fields.

    Represents a full tool record as stored in the database.
    """

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
    """Model for creating a new tool version.

    Used for input validation when creating tool versions.
    """

    tool_id: UUID = Field(
        ...,
        description="ID of the parent tool",
    )
    """Foreign key to the parent tool."""


class ToolVersion(ToolVersionBase, BaseModelWithID):
    """Complete tool version model with all database fields.

    Represents a full tool version record as stored in the database.
    """

    tool_id: UUID = Field(
        ...,
        description="ID of the parent tool",
    )
    """Foreign key to the parent tool."""

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
