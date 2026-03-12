from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text

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
    
    async def get_similar_memories(
        self,
        session: AsyncSession,
        agent_id: int,
        query_vector: List[float],
        top_k: int = 15
    ) -> List[LongTermMemoryModel]:
        """使用 Cosine Distance 獲取最相似的長期記憶
        
        Args:
            session: AsyncSession
            agent_id: Agent ID
            query_vector: 查詢向量
            top_k: 返回前 K 個最相似的記憶
            
        Returns:
            最相似的 LongTermMemoryModel 列表
        """
        # 使用 pgvector 的 cosine distance (<=>) 進行相似度搜索
        # 將向量轉換為 PostgreSQL 數組格式
        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
        
        query = text(f"""
            SELECT id, agent_id, content, vector_content, importance, created_at
            FROM long_term_memory
            WHERE agent_id = :agent_id
              AND vector_content IS NOT NULL
            ORDER BY vector_content <=> :query_vector
            LIMIT :top_k
        """)
        
        result = await session.execute(
            query,
            {"agent_id": agent_id, "query_vector": vector_str, "top_k": top_k}
        )
        
        memories = []
        for row in result:
            # 手動構建 LongTermMemoryModel 對象
            memory = LongTermMemoryModel(
                id=row.id,
                agent_id=row.agent_id,
                content=row.content,
                vector_content=row.vector_content,
                importance=row.importance,
                created_at=row.created_at
            )
            memories.append(memory)
        
        return memories