from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text, update, delete

from db.models import SoulMemoryModel


class SoulMemoryDAO:
    """Soul Memory Data Access Object"""
    
    async def create(
        self,
        session: AsyncSession,
        category: str,
        mem_key: str,
        content: str,
        embedding: Optional[List[float]] = None,
        confidence: float = 0.1,
        status: str = 'staging',
        metadata: Optional[Dict[str, Any]] = None
    ) -> SoulMemoryModel:
        """創建靈魂記憶"""
        new_memory = SoulMemoryModel(
            category=category,
            mem_key=mem_key,
            content=content,
            embedding=embedding,
            confidence=confidence,
            status=status,
            meta_data=metadata
        )
        session.add(new_memory)
        await session.flush()
        await session.refresh(new_memory)
        return new_memory
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[SoulMemoryModel]:
        """根據 ID 獲取靈魂記憶"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_mem_key(self, session: AsyncSession, mem_key: str) -> Optional[SoulMemoryModel]:
        """根據 mem_key 獲取靈魂記憶"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.mem_key == mem_key)
        )
        return result.scalar_one_or_none()
    
    async def get_by_category(self, session: AsyncSession, category: str) -> List[SoulMemoryModel]:
        """根據 category 獲取所有靈魂記憶"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.category == category)
        )
        return result.scalars().all()
    
    async def get_core_memory(self, session: AsyncSession) -> List[SoulMemoryModel]:
        """根據 category 獲取所有靈魂記憶"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.status == "core")
        )
        return result.scalars().all()
    
    async def upsert(
        self,
        session: AsyncSession,
        category: str,
        mem_key: str,
        content: str,
        embedding: Optional[List[float]] = None,
        confidence: float = 0.1,
        status: str = 'staging',
        metadata: Optional[Dict[str, Any]] = None
    ) -> SoulMemoryModel:
        """UPSERT 靈魂記憶（如果 mem_key 存在則更新，否則創建）"""
        existing = await self.get_by_mem_key(session, mem_key)
        
        if existing:
            # 更新現有記錄
            existing.content = content
            if embedding is not None:
                existing.embedding = embedding
            existing.confidence = confidence
            existing.status = status
            if metadata is not None:
                existing.meta_data = metadata
            existing.hit_count += 1
            await session.flush()
            await session.refresh(existing)
            return existing
        else:
            # 創建新記錄
            return await self.create(
                session=session,
                category=category,
                mem_key=mem_key,
                content=content,
                embedding=embedding,
                confidence=confidence,
                status=status,
                metadata=metadata
            )
    
    async def update(
        self,
        session: AsyncSession,
        id: int,
        content: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        confidence: Optional[float] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[SoulMemoryModel]:
        """更新靈魂記憶"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return None
        
        if content is not None:
            existing.content = content
        if embedding is not None:
            existing.embedding = embedding
        if confidence is not None:
            existing.confidence = confidence
        if status is not None:
            existing.status = status
        if metadata is not None:
            existing.meta_data = metadata
        
        existing.hit_count += 1
        await session.flush()
        await session.refresh(existing)
        return existing
    
    async def delete(self, session: AsyncSession, id: int) -> bool:
        """刪除靈魂記憶"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return False
        
        await session.delete(existing)
        await session.flush()
        return True
    
    async def search_by_embedding(
        self,
        session: AsyncSession,
        embedding: List[float],
        category: Optional[str] = None,
        limit: int = 5,
        threshold: float = 0.7
    ) -> List[SoulMemoryModel]:
        """使用向量相似度搜索靈魂記憶"""
        # 將 embedding 轉換為 PostgreSQL 的 vector 格式
        embedding_str = '[' + ','.join(map(str, embedding)) + ']'
        
        query = text(f"""
            SELECT id, category, mem_key, content, embedding, confidence, hit_count, status, last_seen, created_at, metadata
            FROM soul_memory
            WHERE 1 - (embedding <=> :embedding::vector) >= :threshold
            {'AND category = :category' if category else ''}
            ORDER BY 1 - (embedding <=> :embedding::vector) DESC
            LIMIT :limit
        """)
        
        params = {"embedding": embedding_str, "threshold": threshold, "limit": limit}
        if category:
            params["category"] = category
        
        result = await session.execute(query, params)
        rows = result.fetchall()
        
        # 將結果轉換為 SoulMemoryModel 對象
        memories = []
        for row in rows:
            memory = SoulMemoryModel(
                id=row[0],
                category=row[1],
                mem_key=row[2],
                content=row[3],
                embedding=row[4],
                confidence=row[5],
                hit_count=row[6],
                status=row[7],
                last_seen=row[8],
                created_at=row[9],
                metadata=row[10]
            )
            memories.append(memory)
        
        return memories
    
    async def increment_hit_count(self, session: AsyncSession, id: int) -> bool:
        """增加 hit_count"""
        result = await session.execute(
            select(SoulMemoryModel).where(SoulMemoryModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return False
        
        existing.hit_count += 1
        await session.flush()
        return True
    
    async def get_all(self, session: AsyncSession) -> List[SoulMemoryModel]:
        """獲取所有靈魂記憶"""
        result = await session.execute(select(SoulMemoryModel))
        return result.scalars().all()
