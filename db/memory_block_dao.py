from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.models import MemoryBlockModel


class MemoryBlockDAO:
    """Memory Block Data Access Object"""
    
    async def create(
        self,
        session: AsyncSession,
        agent_id: int,
        block_type: str,
        content: Dict[str, Any],
        vector_content: Optional[List[float]] = None,
        is_active: bool = True
    ) -> MemoryBlockModel:
        """創建記憶區塊"""
        new_memory_block = MemoryBlockModel(
            agent_id=agent_id,
            block_type=block_type,
            content=content,
            vector_content=vector_content,
            is_active=is_active
        )
        session.add(new_memory_block)
        await session.flush()
        await session.refresh(new_memory_block)
        return new_memory_block
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[MemoryBlockModel]:
        """根據 ID 獲取記憶區塊"""
        result = await session.execute(
            select(MemoryBlockModel).where(MemoryBlockModel.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_agent_id(self, session: AsyncSession, agent_id: int) -> List[MemoryBlockModel]:
        """根據 agent_id 獲取所有記憶區塊"""
        result = await session.execute(
            select(MemoryBlockModel).where(MemoryBlockModel.agent_id == agent_id)
        )
        return list(result.scalars().all())
    
    async def get_by_agent_id_and_type(
        self,
        session: AsyncSession,
        agent_id: int,
        block_type: str
    ) -> List[MemoryBlockModel]:
        """根據 agent_id 和 block_type 獲取記憶區塊"""
        result = await session.execute(
            select(MemoryBlockModel).where(
                MemoryBlockModel.agent_id == agent_id,
                MemoryBlockModel.block_type == block_type
            )
        )
        return list(result.scalars().all())
    
    async def get_active_by_agent_id_and_type(
        self,
        session: AsyncSession,
        agent_id: int,
        block_type: str
    ) -> List[MemoryBlockModel]:
        """根據 agent_id 和 block_type 獲取活躍的記憶區塊"""
        result = await session.execute(
            select(MemoryBlockModel).where(
                MemoryBlockModel.agent_id == agent_id,
                MemoryBlockModel.block_type == block_type,
                MemoryBlockModel.is_active == True
            )
        )
        return list(result.scalars().all())
    
    async def update(
        self,
        session: AsyncSession,
        id: int,
        content: Optional[Dict[str, Any]] = None,
        vector_content: Optional[List[float]] = None,
        is_active: Optional[bool] = None
    ) -> Optional[MemoryBlockModel]:
        """更新記憶區塊"""
        result = await session.execute(
            select(MemoryBlockModel).where(MemoryBlockModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return None
        
        if content is not None:
            existing.content = content
        if vector_content is not None:
            existing.vector_content = vector_content
        if is_active is not None:
            existing.is_active = is_active
        
        # 更新 updated_at
        from sqlalchemy import func
        existing.updated_at = func.now()
        
        await session.flush()
        await session.refresh(existing)
        return existing
    
    async def delete(self, session: AsyncSession, id: int) -> bool:
        """刪除記憶區塊"""
        result = await session.execute(
            select(MemoryBlockModel).where(MemoryBlockModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return False
        
        await session.delete(existing)
        await session.flush()
        return True
    
    async def deactivate(self, session: AsyncSession, id: int) -> bool:
        """停用記憶區塊（軟刪除）"""
        result = await session.execute(
            select(MemoryBlockModel).where(MemoryBlockModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return False
        
        existing.is_active = False
        await session.flush()
        return True
