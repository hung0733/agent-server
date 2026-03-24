# pyright: reportMissingImports=false, reportUndefinedVariable=false
"""
SQLAlchemy entity model for memory_blocks table.

Import path: db.entity.memory_block_entity
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.entity.base import EntityBase as Base


def gen_random_uuid() -> UUID:
    return uuid4()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MemoryBlock(Base):
    """Persistent memory entry for an agent instance.

    Table: memory_blocks
    """

    __tablename__ = "memory_blocks"

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

    memory_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

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
        Index("idx_memory_blocks_agent_instance_id", "agent_instance_id"),
        {"extend_existing": True},
    )
