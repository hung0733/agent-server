from pydantic import BaseModel, ConfigDict


class UserAccCreate(BaseModel):
    user_id: str
    name: str
    phoneno: str | None = None


class UserAccUpdate(BaseModel):
    user_id: str | None = None
    name: str | None = None
    phoneno: str | None = None


class UserAccRead(UserAccCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
