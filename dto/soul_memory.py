import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from db.models import SoulMemoryModel


class SoulMemoryDTO:
    """靈魂記憶數據傳輸對象"""
    
    id: int | None
    category: str  # 'soul', 'identity', 'user_profile'
    mem_key: str  # 用於 UPSERT 的唯一鍵
    content: str
    embedding: List[float] | None
    confidence: float
    hit_count: int
    status: str  # 'staging', 'active', 'archived'
    last_seen: datetime | None
    created_at: datetime | None
    meta_data: Dict[str, Any] | None
    
    def __init__(
        self,
        id: int | None = None,
        category: str = 'soul',
        mem_key: str = '',
        content: str = '',
        embedding: List[float] | None = None,
        confidence: float = 0.1,
        hit_count: int = 1,
        status: str = 'staging',
        last_seen: datetime | None = None,
        created_at: datetime | None = None,
        meta_data: Dict[str, Any] | None = None
    ) -> None:
        self.id = id
        self.category = category
        self.mem_key = mem_key
        self.content = content
        self.embedding = embedding
        self.confidence = confidence
        self.hit_count = hit_count
        self.status = status
        self.last_seen = last_seen
        self.created_at = created_at
        self.meta_data = meta_data
    
    @classmethod
    def from_model(cls, model: SoulMemoryModel) -> 'SoulMemoryDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=model.id,
            category=model.category,
            mem_key=model.mem_key,
            content=model.content,
            embedding=model.embedding,
            confidence=model.confidence,
            hit_count=model.hit_count,
            status=model.status,
            last_seen=model.last_seen,
            created_at=model.created_at,
            meta_data=model.meta_data
        )
        
    @classmethod
    def from_json(
        cls,
        category: str,
        data: Dict[str, Any],
        embedding_vector: List[float]
    ) -> 'SoulMemoryDTO':
        """從 JSON 數據和嵌入向量構建 SoulMemoryDTO。
        
        Args:
            category: 記憶類別 ('soul', 'identity', 'user_profile')
            data: 包含記憶數據的字典，應包含 key, content, confidence_score, reason 等字段
            embedding_vector: 記憶的向量表示
            
        Returns:
            SoulMemoryDTO 實例
            
        Raises:
            ValueError: 當必要字段缺失或數據類型不正確時
        """
        # 驗證必要字段
        if not isinstance(data, dict):
            raise ValueError(f"data 必須是字典類型，收到：{type(data)}")
        
        # 提取並驗證字段
        mem_key = data.get("key", "")
        if not mem_key:
            raise ValueError("記憶的 'key' 字段不能為空")
        
        content = data.get("content", "")
        if not content:
            raise ValueError("記憶的 'content' 字段不能為空")
        
        # 處理置信度分數，確保為 float 類型
        confidence_raw = data.get("confidence_score", 0.1)
        try:
            confidence = float(confidence_raw) if confidence_raw is not None else 0.1
        except (TypeError, ValueError):
            confidence = 0.1
        
        # 構建元數據，僅在 reason 存在時才包含
        reason = data.get("reason")
        meta_data: Optional[Dict[str, Any]] = {"reason": reason} if reason is not None else None

        return cls(
            category=category,
            mem_key=mem_key,
            content=content,
            embedding=embedding_vector,
            confidence=confidence,
            status="core",
            meta_data=meta_data
        )
                        