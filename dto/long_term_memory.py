from datetime import datetime
from typing import Any, Dict


class LongTermMemoryDTO:
    """長期記憶數據傳輸對象"""
    
    id: int | None
    agent_id: int
    content: Dict[str, Any]
    vector_content: str | None
    importance: int
    created_at: datetime | None
    
    def __init__(
        self,
        id: int | None = None,
        agent_id: int | None = None,
        content: Dict[str, Any] | None = None,
        vector_content: str | None = None,
        importance: int = 5,
        created_at: datetime | None = None
    ) -> None:
        self.id = id
        self.agent_id = agent_id or 0
        self.content = content or {}
        self.vector_content = vector_content
        self.importance = importance
        self.created_at = created_at
    
    @classmethod
    def from_model(cls, model: Any) -> 'LongTermMemoryDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=model.id,
            agent_id=model.agent_id,
            content=model.content,
            vector_content=model.vector_content,
            importance=model.importance,
            created_at=model.created_at
        )