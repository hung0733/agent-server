# pyright: reportMissingImports=false
"""
Pydantic DTOs for memory_blocks table.

Import path: db.dto.memory_block_dto
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def gen_random_uuid() -> UUID:
    return uuid4()


class MemoryBlockBase(BaseModel):
    memory_type: str = Field(..., description="Type/category of this memory block")
    content: str = Field(..., description="Memory content")
    version: int = Field(default=1)
    is_active: bool = Field(default=True)

    model_config = ConfigDict(extra="ignore")


class MemoryBlockCreate(MemoryBlockBase):
    agent_instance_id: UUID


class MemoryBlockUpdate(BaseModel):
    id: UUID
    memory_type: Optional[str] = None
    content: Optional[str] = None
    version: Optional[int] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(extra="ignore")


class MemoryBlock(MemoryBlockBase):
    id: UUID = Field(default_factory=gen_random_uuid)
    agent_instance_id: UUID
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    model_config = ConfigDict(extra="ignore", from_attributes=True)
