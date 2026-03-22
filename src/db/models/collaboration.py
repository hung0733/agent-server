# pyright: reportMissingImports=false
"""
Pydantic models for collaboration sessions and agent messages.

This module provides Pydantic v2 models for validation and serialization
of collaboration session and agent message data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from db.models.base import BaseModelWithID, now_utc
from db.types import gen_random_uuid


class CollaborationStatusEnum(str):
    """Collaboration session status values."""
    active = "active"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class MessageRedactionLevelEnum(str):
    """Message redaction level values."""
    none = "none"
    partial = "partial"
    full = "full"


class MessageTypeEnum(str):
    """Agent message type values."""
    request = "request"
    response = "response"
    notification = "notification"
    ack = "ack"
    tool_call = "tool_call"
    tool_result = "tool_result"


class CollaborationSessionBase(BaseModel):
    """Base model with common collaboration session fields."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional human-readable name for the collaboration session",
    )
    """Session name."""
    
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Unique session identifier with prefixes (session-{uuid}, default-{uuid}, ghost-{uuid}, refl-{uuid})",
    )
    """Unique session ID."""
    
    status: str = Field(
        default=CollaborationStatusEnum.active,
        description="Current status of the collaboration session",
    )
    """Session status."""
    
    involves_secrets: bool = Field(
        default=False,
        description="Whether this collaboration involves sensitive/secrets data",
    )
    """Secrets involvement flag."""
    
    context_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field storing shared session context",
    )
    """Shared session context."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "Research Collaboration",
                "session_id": "session-550e8400-e29b-41d4-a716-446655440000",
                "status": "active",
                "involves_secrets": False,
                "context_json": {"topic": "research", "agents": 2},
            }
        }
    )


class CollaborationSessionCreate(CollaborationSessionBase):
    """Model for creating a new collaboration session.
    
    Used for input validation when creating collaboration sessions.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
    main_agent_id: UUID = Field(
        ...,
        description="ID of the main coordinating agent instance",
    )
    """Foreign key to the main agent."""


class CollaborationSession(CollaborationSessionBase, BaseModelWithID):
    """Complete collaboration session model with all database fields.
    
    Represents a full collaboration session record as stored in the database.
    """
    
    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Foreign key to the owning user."""
    
    main_agent_id: UUID = Field(
        ...,
        description="ID of the main coordinating agent instance",
    )
    """Foreign key to the main agent."""
    
    ended_at: Optional[datetime] = Field(
        default=None,
        description="Session end timestamp (UTC)",
    )
    """Session end timestamp."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "main_agent_id": "660f9500-f39c-51e5-b827-557766550001",
                "name": "Research Collaboration",
                "session_id": "session-550e8400-e29b-41d4-a716-446655440000",
                "status": "active",
                "involves_secrets": False,
                "context_json": {"topic": "research", "agents": 2},
                "created_at": "2026-03-22T12:00:00Z",
                "ended_at": None,
                "updated_at": "2026-03-22T12:00:00Z",
            }
        }
    )


class AgentMessageBase(BaseModel):
    """Base model with common agent message fields."""
    
    step_id: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional step identifier grouping related messages in an interaction flow",
    )
    """Step ID for grouping related messages."""
    
    message_type: str = Field(
        default=MessageTypeEnum.request,
        description="Type of the message (request/response/notification/ack/tool_call/tool_result)",
    )
    """Message type."""
    
    content_json: dict[str, Any] = Field(
        ...,
        description="JSONB field storing structured message content",
    )
    """Message content."""
    
    redaction_level: str = Field(
        default=MessageRedactionLevelEnum.none,
        description="Redaction level for message content",
    )
    """Content redaction level."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "step_id": "step-001",
                "message_type": "request",
                "content_json": {"action": "search", "query": "example"},
                "redaction_level": "none",
            }
        }
    )


class AgentMessageCreate(AgentMessageBase):
    """Model for creating a new agent message.
    
    Used for input validation when creating agent messages.
    """
    
    collaboration_id: UUID = Field(
        ...,
        description="ID of the collaboration session",
    )
    """Foreign key to the collaboration session."""
    
    sender_agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the sending agent instance",
    )
    """Foreign key to the sender agent."""
    
    receiver_agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the receiving agent instance",
    )
    """Foreign key to the receiver agent."""


class AgentMessage(AgentMessageBase, BaseModelWithID):
    """Complete agent message model with all database fields.
    
    Represents a full agent message record as stored in the database.
    """
    
    collaboration_id: UUID = Field(
        ...,
        description="ID of the collaboration session",
    )
    """Foreign key to the collaboration session."""
    
    sender_agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the sending agent instance",
    )
    """Foreign key to the sender agent."""
    
    receiver_agent_id: Optional[UUID] = Field(
        default=None,
        description="ID of the receiving agent instance",
    )
    """Foreign key to the receiver agent."""
    
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "collaboration_id": "550e8400-e29b-41d4-a716-446655440000",
                "step_id": "step-001",
                "sender_agent_id": "660f9500-f39c-51e5-b827-557766550001",
                "receiver_agent_id": "660f9500-f39c-51e5-b827-557766550002",
                "message_type": "request",
                "content_json": {"action": "search", "query": "example"},
                "redaction_level": "none",
                "created_at": "2026-03-22T12:00:00Z",
            }
        }
    )
