from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LlmUsageCreate(BaseModel):
    llm_endpoint_id: int
    date_time: datetime | None = None
    total_token: int = 0
    in_token: int = 0
    cached_in_token: int = 0
    out_token: int = 0


class LlmUsageUpdate(BaseModel):
    llm_endpoint_id: int | None = None
    date_time: datetime | None = None
    total_token: int | None = None
    in_token: int | None = None
    cached_in_token: int | None = None
    out_token: int | None = None


class LlmUsageRead(LlmUsageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
