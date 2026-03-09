from pydantic import BaseModel
from typing import Optional


class SessionCreate(BaseModel):
    """Session 創建請求"""
    agent_id: str              # Agent's unique identifier (string)
    name: str                  # Display name
    
    class Config:
        from_attributes = True


class SessionUpdate(BaseModel):
    """Session 更新請求"""
    name: Optional[str] = None


class SessionOut(BaseModel):
    """Session 響應"""
    id: int                    # DB primary key
    agent_id: int              # Agent's DB ID (for internal use)
    session_id: str            # Unique identifier
    name: str
    
    class Config:
        from_attributes = True