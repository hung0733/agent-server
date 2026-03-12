from datetime import datetime
from typing import Any, Dict, List, Optional


class MemoryBlockDTO:
    """記憶區塊數據傳輸對象"""
    
    id: int | None
    agent_id: int
    block_type: str  # 'soul', 'identity', 'user_profile'
    content: Dict[str, Any]
    vector_content: List[float] | None
    is_active: bool
    updated_at: datetime | None
    
    def __init__(
        self,
        id: int | None = None,
        agent_id: int | None = None,
        block_type: str | None = None,
        content: Dict[str, Any] | None = None,
        vector_content: List[float] | None = None,
        is_active: bool = True,
        updated_at: datetime | None = None
    ) -> None:
        self.id = id
        self.agent_id = agent_id or 0
        self.block_type = block_type or ""
        self.content = content or {}
        self.vector_content = vector_content
        self.is_active = is_active
        self.updated_at = updated_at
    
    @classmethod
    def from_model(cls, model: Any) -> 'MemoryBlockDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=model.id,
            agent_id=model.agent_id,
            block_type=model.block_type,
            content=model.content,
            vector_content=model.vector_content,
            is_active=model.is_active,
            updated_at=model.updated_at
        )
