
from typing import List, cast
from sqlalchemy import DateTime, func
from db.models import MessageModel

class MessageDTO:
    msg_type : str
    is_think_mode : bool
    sent_by : str
    content : str
    date : DateTime
    
    def __init__(self, msg_type : str, is_think_mode : bool, sent_by : str, date : DateTime, content : str) -> None:
        self.msg_type = msg_type
        self.is_think_mode = is_think_mode
        self.sent_by = sent_by
        self.date = date
        self.content = content
    
    def to_msg(self):
        return {"role": self.sent_by, "content": self.content}
        
    @classmethod
    def get(cls, m : MessageModel):
        return cls(
            msg_type = m.msg_type,
            is_think_mode = m.is_think_mode,
            sent_by = m.sent_by,
            date = m.create_date,
            content = m.content
        )
        
    @classmethod
    def get_user_msg(cls, user_input: str, is_think_mode : bool):
        return cls(
            msg_type = "user_message",
            is_think_mode = is_think_mode,
            sent_by = "user",
            date = cast(DateTime, func.now()),
            content = user_input
        )
    
        
    @classmethod
    def get_assistant_msg(cls, user_input: str, is_think_mode : bool):
        return cls(
            msg_type = "assistant_message",
            is_think_mode = is_think_mode,
            sent_by = "assistant",
            date = cast(DateTime, func.now()),
            content = user_input
        )
        
    @classmethod
    def get_reasoning_msg(cls, user_input: str, is_think_mode : bool):
        return cls(
            msg_type = "reasoning_message",
            is_think_mode = is_think_mode,
            sent_by = "assistant",
            date = cast(DateTime, func.now()),
            content = user_input
        )