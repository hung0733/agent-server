from pydantic import BaseModel, ConfigDict


class AgentSessionCreate(BaseModel):
    recv_agent_id: int
    session_id: str
    name: str
    session_type: str
    sender_agent_id: int
    is_confidential: bool = False


class AgentSessionUpdate(BaseModel):
    recv_agent_id: int | None = None
    session_id: str | None = None
    name: str | None = None
    session_type: str | None = None
    sender_agent_id: int | None = None
    is_confidential: bool | None = None


class AgentSessionRead(AgentSessionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
