# pyright: reportMissingImports=false
"""
Pydantic models for audit logging.

This module provides Pydantic v2 models for validation and serialization
of audit log data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from db.models.base import BaseModelWithID, now_utc
from db.types import ActorType, gen_random_uuid


class AuditLogBase(BaseModel):
    """Base model with common audit log fields."""
    
    actor_type: ActorType = Field(
        ...,
        description="Type of actor performing the action (user/agent/system)",
    )
    """Type of actor."""
    
    actor_id: UUID = Field(
        ...,
        description="ID of the actor that performed the action",
    )
    """Actor identifier."""
    
    action: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="The action performed (e.g., create/update/delete/execute)",
    )
    """Action type."""
    
    resource_type: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Type of resource affected (e.g., user, task, agent)",
    )
    """Resource type."""
    
    resource_id: UUID = Field(
        ...,
        description="ID of the resource affected by the action",
    )
    """Resource identifier."""
    
    user_id: Optional[UUID] = Field(
        default=None,
        description="Optional reference to the user who performed the action",
    )
    """Associated user ID if applicable."""
    
    old_values: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Previous state of the resource before the action",
    )
    """Previous state (for updates/deletes)."""
    
    new_values: Optional[Dict[str, Any]] = Field(
        default=None,
        description="New state of the resource after the action",
    )
    """New state (for creates/updates)."""
    
    ip_address: Optional[str] = Field(
        default=None,
        description="IP address from which the action originated",
    )
    """Origin IP address."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "actor_type": "user",
                "actor_id": "550e8400-e29b-41d4-a716-446655440000",
                "action": "update",
                "resource_type": "task",
                "resource_id": "660f9500-f39c-51e5-b827-557766550001",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "old_values": {"status": "pending"},
                "new_values": {"status": "running"},
                "ip_address": "192.168.1.1",
            }
        }
    )


class AuditLogCreate(AuditLogBase):
    """Model for creating a new audit log entry.
    
    Used for input validation when recording audit events.
    """
    
    pass


class AuditLog(AuditLogBase, BaseModelWithID):
    """Complete audit log model with all database fields.
    
    Represents a full audit log record as stored in the database.
    """
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "actor_type": "user",
                "actor_id": "550e8400-e29b-41d4-a716-446655440000",
                "action": "update",
                "resource_type": "task",
                "resource_id": "660f9500-f39c-51e5-b827-557766550001",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "old_values": {"status": "pending"},
                "new_values": {"status": "running"},
                "ip_address": "192.168.1.1",
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )
