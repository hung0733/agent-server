from pydantic import BaseModel
from typing import Optional

class AgentCreate(BaseModel):
    agent_id: str
    name: str
    sys_prompt: Optional[str] = None

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    sys_prompt: Optional[str] = None

class AgentOut(BaseModel):
    id: int
    agent_id: str
    name: str
    sys_prompt: Optional[str] = None

    class Config:
        from_attributes = True