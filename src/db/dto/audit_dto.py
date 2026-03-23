# pyright: reportMissingImports=false
"""
Pydantic DTOs for audit logging.

This module provides Pydantic v2 DTOs for validation and serialization
of audit log data. Follows the Base/Create/Complete pattern.

Note: Audit logs are append-only, so there is no Update DTO.

Import path: src.db.dto.audit_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Dict, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict, field_validator

from db.types import ActorType


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


# =============================================================================
# Audit Log DTOs
# =============================================================================

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
    """DTO for creating a new audit log entry.
    
    Used for input validation when recording audit events.
    Note: Audit logs are append-only - once created, they cannot be updated.
    """
    
    pass


class AuditLog(AuditLogBase):
    """Complete audit log DTO with all database fields.
    
    Represents a full audit log record as stored in the database.
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
    
    @field_validator('ip_address', mode='before')
    @classmethod
    def convert_ip_address(cls, v: Any) -> Optional[str]:
        """Convert IPv4Address/IPv6Address to string.
        
        PostgreSQL INET type returns ipaddress objects, but we store as string.
        """
        if v is None:
            return None
        if isinstance(v, (IPv4Address, IPv6Address)):
            return str(v)
        return v
    
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