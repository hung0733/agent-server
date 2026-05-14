from pydantic import BaseModel, ConfigDict


class LlmEndpointCreate(BaseModel):
    user_id: int
    name: str
    endpoint: str
    enc_key: str | None = None
    model_name: str | None = None
    max_token: int | None = None


class LlmEndpointUpdate(BaseModel):
    user_id: int | None = None
    name: str | None = None
    endpoint: str | None = None
    enc_key: str | None = None
    model_name: str | None = None
    max_token: int | None = None


class LlmEndpointRead(LlmEndpointCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
