from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MemoryBlockCreate(BaseModel):
    agent_id: int
    memory_type: str
    content: str | None = None


class MemoryBlockUpdate(BaseModel):
    agent_id: int | None = None
    memory_type: str | None = None
    content: str | None = None


class MemoryBlockRead(MemoryBlockCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_upd_dt: datetime
