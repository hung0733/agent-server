from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.models import LongTermMemoryModel


class LongTermMemoryDAO:
    """Long Term Memory Data Access Object"""
    
    async def create(
        self,
        session: AsyncSession,
        agent_id: int,
        content: Dict[str, Any],
        vector_content: Optional[List[float]] = None,
        importance: int = 5
    ) -> LongTermMemoryModel:
        """創建長期記憶"""
        new_memory = LongTermMemoryModel(
            agent_id=agent_id,
            content=content,
            vector_content=vector_content,
            importance=importance
        )
        session.add(new_memory)
        await session.flush()
        await session.refresh(new_memory)
        return new_memory
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[LongTermMemoryModel]:
        """根據 ID 獲取長期記憶"""
        result = await session.execute(
            select(LongTermMemoryModel).where(LongTermMemoryModel.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_agent_id(self, session: AsyncSession, agent_id: int) -> List[LongTermMemoryModel]:
        """根據 agent_id 獲取所有長期記憶"""
        result = await session.execute(
            select(LongTermMemoryModel).where(LongTermMemoryModel.agent_id == agent_id)
        )
        return result.scalars().all()
    
    async def update(
        self,
        session: AsyncSession,
        id: int,
        content: Optional[Dict[str, Any]] = None,
        vector_content: Optional[List[float]] = None,
        importance: Optional[int] = None
    ) -> Optional[LongTermMemoryModel]:
        """更新長期記憶"""
        result = await session.execute(
            select(LongTermMemoryModel).where(LongTermMemoryModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return None
        
        if content is not None:
            existing.content = content
        if vector_content is not None:
            existing.vector_content = vector_content
        if importance is not None:
            existing.importance = importance
        
        await session.flush()
        await session.refresh(existing)
        return existing
    
    async def delete(self, session: AsyncSession, id: int) -> bool:
        """刪除長期記憶"""
        result = await session.execute(
            select(LongTermMemoryModel).where(LongTermMemoryModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return False
        
        await session.delete(existing)
        await session.flush()
        return True
    
    async def get_unsummarized_messages(
        self,
        session: AsyncSession,
        agent_id: int
    ) -> List[LongTermMemoryModel]:
        """獲取未鞏固的訊息（用於總結）"""
        # 這個方法需要配合 MessageModel 的 long_term_mem_id IS NULL 條件
        # 由於 SQLAlchemy 查詢複雜條件，建議在 DAO 層使用原始 SQL 或結合 MessageDAO
        result = await session.execute(
            select(LongTermMemoryModel)
            .join(LongTermMemoryModel.messages)
            .where(LongTermMemoryModel.agent_id == agent_id)
            .where(LongTermMemoryModel.messages.long_term_mem_id.is_(None))
        )
        return list(result.scalars().unique())