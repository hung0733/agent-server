from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ShortTermMemCreate(BaseModel):
    session_id: int
    content: str | None = None
    token: int | None = None


class ShortTermMemUpdate(BaseModel):
    session_id: int | None = None
    content: str | None = None
    token: int | None = None


class ShortTermMemRead(ShortTermMemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    create_dt: datetime
