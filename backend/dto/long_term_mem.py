from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LongTermMemCreate(BaseModel):
    agent_id: int
    content: str | None = None
    token: int | None = None


class LongTermMemUpdate(BaseModel):
    agent_id: int | None = None
    content: str | None = None
    token: int | None = None


class LongTermMemRead(LongTermMemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    create_dt: datetime
