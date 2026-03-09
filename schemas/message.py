from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MessageCreate(BaseModel):
    """Message 創建請求"""
    session_id: str            # Session's unique identifier
    step_id: str               # Conversation step ID (group related messages)
    msg_type: str              # e.g., "user_message", "assistant_message"
    content: str
    is_think_mode: bool = False
    sent_by: str               # e.g., "user", "assistant"
    token: int = 0


class MessageOut(BaseModel):
    """Message 響應"""
    id: int                    # DB primary key
    agent_id: int              # Agent's DB ID
    session_id: int            # Session's DB ID
    step_id: str
    msg_id: str                # Unique message identifier
    msg_type: str
    create_date: datetime
    content: str
    is_think_mode: bool
    sent_by: str
    token: int
    
    class Config:
        from_attributes = True