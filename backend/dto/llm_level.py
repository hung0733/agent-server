from pydantic import BaseModel, ConfigDict


class LlmLevelCreate(BaseModel):
    llm_group_id: int
    llm_endpoint_id: int
    level: int
    is_confidential: bool = False
    seq_no: int = 0


class LlmLevelUpdate(BaseModel):
    llm_group_id: int | None = None
    llm_endpoint_id: int | None = None
    level: int | None = None
    is_confidential: bool | None = None
    seq_no: int | None = None


class LlmLevelRead(LlmLevelCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
