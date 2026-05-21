from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentMsgHistCreate(BaseModel):
    session_id: int
    step_id: str
    sender: str
    msg_type: str
    content: str | None = None
    token: int | None = None
    meta_data: str | None = None
    model_name: str | None = None


class AgentMsgHistUpdate(BaseModel):
    session_id: int | None = None
    step_id: str | None = None
    sender: str | None = None
    msg_type: str | None = None
    content: str | None = None
    token: int | None = None
    meta_data: str | None = None
    model_name: str | None = None


class AgentMsgHistRead(AgentMsgHistCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    create_dt: datetime
