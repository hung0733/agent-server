from pydantic import BaseModel
from typing import Optional

class AgentCreate(BaseModel):
    name: str
    sys_prompt: Optional[str] = None
    brain_slot_id : int = 0
    sum_slot_id : int = 0

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    sys_prompt: Optional[str] = None
    brain_slot_id : int = 0
    sum_slot_id : int = 0

class AgentOut(BaseModel):
    id: int
    agent_id: str
    name: str
    sys_prompt: Optional[str] = None
    brain_slot_id : int = 0
    sum_slot_id : int = 0

    class Config:
        from_attributes = True