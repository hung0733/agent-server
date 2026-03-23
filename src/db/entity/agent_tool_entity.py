# pyright: reportMissingImports=false, reportUndefinedVariable=false
"""
SQLAlchemy entity models for agent–tool associations.

Two-level design:
- AgentTypeTool: defines which tools an agent type can use by default
- AgentInstanceTool: per-instance overrides (add extra tools or disable type-level tools)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.entity.base import EntityBase as Base


def gen_random_uuid() -> UUID:
    return uuid4()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AgentTypeTool(Base):
    """Association between an agent type and a tool.

    Defines the default tool set that all instances of an agent type inherit.

    Table: agent_type_tools
    """

    __tablename__ = "agent_type_tools"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=gen_random_uuid,
        server_default=func.gen_random_uuid(),
    )

    agent_type_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Foreign key to agent_types."""

    tool_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Foreign key to tools."""

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    """Whether this association is active."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("agent_type_id", "tool_id", name="uq_agent_type_tools"),
        Index("idx_att_agent_type", "agent_type_id"),
        Index("idx_att_tool", "tool_id"),
        Index("idx_att_active", "is_active"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<AgentTypeTool(id={self.id}, agent_type_id={self.agent_type_id}, "
            f"tool_id={self.tool_id}, is_active={self.is_active})>"
        )


class AgentInstanceTool(Base):
    """Per-instance tool override.

    An instance can:
    - Add a tool not in the type-level list (is_enabled=True, new tool_id)
    - Disable a type-level tool (is_enabled=False)
    - Override tool config for this instance (config_override)

    Table: agent_instance_tools
    """

    __tablename__ = "agent_instance_tools"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=gen_random_uuid,
        server_default=func.gen_random_uuid(),
    )

    agent_instance_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Foreign key to agent_instances."""

    tool_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Foreign key to tools."""

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    """False = disable a tool inherited from the agent type."""

    config_override: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    """Instance-specific tool configuration overrides."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        server_default=func.now(),
        onupdate=now_utc,
    )

    __table_args__ = (
        UniqueConstraint("agent_instance_id", "tool_id", name="uq_agent_instance_tools"),
        Index("idx_ait_instance", "agent_instance_id"),
        Index("idx_ait_tool", "tool_id"),
        Index("idx_ait_enabled", "is_enabled"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<AgentInstanceTool(id={self.id}, agent_instance_id={self.agent_instance_id}, "
            f"tool_id={self.tool_id}, is_enabled={self.is_enabled})>"
        )
