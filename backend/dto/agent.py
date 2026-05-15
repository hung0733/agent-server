from pydantic import BaseModel, ConfigDict


class AgentCreate(BaseModel):
    user_id: int
    agent_id: str
    name: str
    is_active: bool = True
    llm_group_id: int
    agent_type: str
    is_sub_agent: bool = False
    phone_no: str | None = None
    whatsapp_key: str | None = None
    whatsapp_instance: str | None = None


class AgentUpdate(BaseModel):
    user_id: int | None = None
    agent_id: str | None = None
    name: str | None = None
    is_active: bool | None = None
    llm_group_id: int | None = None
    agent_type: str | None = None
    is_sub_agent: bool | None = None
    phone_no: str | None = None
    whatsapp_key: str | None = None
    whatsapp_instance: str | None = None


class AgentRead(AgentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
