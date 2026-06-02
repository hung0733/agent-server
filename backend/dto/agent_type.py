from pydantic import BaseModel, ConfigDict


class AgentTypeCreate(BaseModel):
    code: str
    name: str | None = None


class AgentTypeUpdate(BaseModel):
    code: str | None = None
    name: str | None = None


class AgentTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
