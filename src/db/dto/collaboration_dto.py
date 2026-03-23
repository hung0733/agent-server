# pyright: reportMissingImports=false
"""
Pydantic DTOs for collaboration sessions and agent messages.

This module provides Pydantic v2 DTOs for validation and serialization
of collaboration session and agent message data. Follows the Base/Create/Update/Complete pattern.

Import path: db.dto.collaboration_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from db.types import CollaborationStatus, MessageRedactionLevel, MessageType


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    """Generate a random UUID v4."""
    return uuid4()


# =============================================================================
# CollaborationSession DTOs
# =============================================================================

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
    
    status: CollaborationStatus = Field(
        default=CollaborationStatus.active,
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
    """DTO for creating a new collaboration session.
    
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
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "user_id": "440d7300-d28a-30c3-9605-335544440000",
                "main_agent_id": "660f9500-f39c-51e5-b827-557766550001",
                "name": "Research Collaboration",
                "session_id": "session-550e8400-e29b-41d4-a716-446655440000",
                "status": "active",
                "involves_secrets": False,
                "context_json": {"topic": "research", "agents": 2},
            }
        }
    )


class CollaborationSessionUpdate(BaseModel):
    """DTO for updating an existing collaboration session.
    
    All fields are optional to allow partial updates.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the collaboration session to update",
    )
    """ID of session to update (required)."""
    
    name: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional human-readable name for the collaboration session",
    )
    """Session name."""
    
    status: Optional[CollaborationStatus] = Field(
        default=None,
        description="Current status of the collaboration session",
    )
    """Session status."""
    
    involves_secrets: Optional[bool] = Field(
        default=None,
        description="Whether this collaboration involves sensitive/secrets data",
    )
    """Secrets involvement flag."""
    
    context_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field storing shared session context",
    )
    """Shared session context."""
    
    ended_at: Optional[datetime] = Field(
        default=None,
        description="Session end timestamp (UTC)",
    )
    """Session end timestamp."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "ended_at": "2026-03-22T12:30:00Z",
            }
        }
    )


class CollaborationSession(CollaborationSessionBase):
    """Complete collaboration session DTO with all database fields.
    
    Represents a full collaboration session record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
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


# =============================================================================
# AgentMessage DTOs
# =============================================================================

class AgentMessageBase(BaseModel):
    """Base model with common agent message fields."""
    
    step_id: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional step identifier grouping related messages in an interaction flow",
    )
    """Step ID for grouping related messages."""
    
    message_type: MessageType = Field(
        default=MessageType.request,
        description="Type of the message (request/response/notification/ack/tool_call/tool_result)",
    )
    """Message type."""
    
    content_json: dict[str, Any] = Field(
        ...,
        description="JSONB field storing structured message content",
    )
    """Message content."""
    
    redaction_level: MessageRedactionLevel = Field(
        default=MessageRedactionLevel.none,
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
    """DTO for creating a new agent message.
    
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
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "collaboration_id": "550e8400-e29b-41d4-a716-446655440000",
                "step_id": "step-001",
                "sender_agent_id": "660f9500-f39c-51e5-b827-557766550001",
                "receiver_agent_id": "660f9500-f39c-51e5-b827-557766550002",
                "message_type": "request",
                "content_json": {"action": "search", "query": "example"},
                "redaction_level": "none",
            }
        }
    )


class AgentMessageUpdate(BaseModel):
    """DTO for updating an existing agent message.
    
    All fields are optional to allow partial updates.
    """
    
    id: UUID = Field(
        ...,
        description="ID of the agent message to update",
    )
    """ID of message to update (required)."""
    
    step_id: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional step identifier grouping related messages",
    )
    """Step ID for grouping related messages."""
    
    message_type: Optional[MessageType] = Field(
        default=None,
        description="Type of the message",
    )
    """Message type."""
    
    content_json: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSONB field storing structured message content",
    )
    """Message content."""
    
    redaction_level: Optional[MessageRedactionLevel] = Field(
        default=None,
        description="Redaction level for message content",
    )
    """Content redaction level."""
    
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "770g0600-g40d-62f6-c938-668877660002",
                "content_json": {"action": "updated_search", "query": "new query"},
                "redaction_level": "partial",
            }
        }
    )


class AgentMessage(AgentMessageBase):
    """Complete agent message DTO with all database fields.
    
    Represents a full agent message record as stored in the database.
    Used as the return type from DAO methods.
    """
    
    id: UUID = Field(
        default_factory=gen_random_uuid,
        description="Unique identifier (UUID v4)",
    )
    """Primary key - auto-generated UUID v4."""
    
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