
from datetime import datetime
from db.models import MessageModel


class MessageDTO:
    """Message 數據傳輸對象"""
    id: int                    # DB primary key (int)
    msg_type: str              # e.g., "user_message", "assistant_message"
    is_think_mode: bool        # Whether this message is in think mode
    sent_by: str               # Who sent the message ("user" or "assistant")
    content: str               # Message content
    date: datetime             # Creation timestamp
    token: int                 # Token count
    step_id: str | None        # Conversation step ID (group related messages)
    
    def __init__(
        self,
        id: int | None = None,
        msg_type: str | None = None,
        is_think_mode: bool = False,
        sent_by: str | None = None,
        date: datetime | None = None,
        content: str | None = None,
        token: int = 0,
        step_id: str | None = None
    ) -> None:
        self.id = id
        self.msg_type = msg_type or ""
        self.is_think_mode = is_think_mode
        self.sent_by = sent_by or ""
        self.date = date or datetime.now()
        self.content = content or ""
        self.token = token
        self.step_id = step_id
    
    def to_msg(self) -> dict:
        """Convert to chat message format"""
        return {"role": self.sent_by, "content": self.content}
    
    @classmethod
    def from_model(cls, m: MessageModel) -> 'MessageDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=m.id,
            msg_type=m.msg_type,
            is_think_mode=m.is_think_mode,
            sent_by=m.sent_by,
            date=m.create_date,
            content=m.content,
            token=m.token,
            step_id=m.step_id
        )
    
    @classmethod
    def get(cls, m: MessageModel) -> 'MessageDTO':
        """Deprecated: Use from_model instead"""
        return cls.from_model(m)
        
    @classmethod
    def get_user_msg(cls, user_input: str, is_think_mode : bool, token: int = 0):
        return cls(
            msg_type = "user_message",
            is_think_mode = is_think_mode,
            sent_by = "user",
            date = datetime.now(),
            content = user_input,
            token = token
        )
    
        
    @classmethod
    def get_assistant_msg(cls, user_input: str, is_think_mode : bool, token: int = 0):
        return cls(
            msg_type = "assistant_message",
            is_think_mode = is_think_mode,
            sent_by = "assistant",
            date = datetime.now(),
            content = user_input,
            token = token
        )
        
    @classmethod
    def get_reasoning_msg(cls, user_input: str, is_think_mode : bool, token: int = 0):
        return cls(
            msg_type = "reasoning_message",
            is_think_mode = is_think_mode,
            sent_by = "assistant",
            date = datetime.now(),
            content = user_input,
            token = token
        )
