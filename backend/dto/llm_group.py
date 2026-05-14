from pydantic import BaseModel, ConfigDict


class LlmGroupCreate(BaseModel):
    user_id: int
    name: str


class LlmGroupUpdate(BaseModel):
    user_id: int | None = None
    name: str | None = None


class LlmGroupRead(LlmGroupCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
