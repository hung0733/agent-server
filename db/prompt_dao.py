from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.models import PromptModel


class PromptDAO:
    """Prompt Data Access Object"""
    
    async def create(
        self,
        session: AsyncSession,
        prompt_type: str,
        prompt: str,
        retry_prompt: Optional[str] = None
    ) -> PromptModel:
        """創建 Prompt"""
        new_prompt = PromptModel(
            prompt_type=prompt_type,
            prompt=prompt,
            retry_prompt=retry_prompt
        )
        session.add(new_prompt)
        await session.flush()
        await session.refresh(new_prompt)
        return new_prompt
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[PromptModel]:
        """根據 DB ID 獲取 Prompt"""
        result = await session.execute(
            select(PromptModel).where(PromptModel.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_code(self, session: AsyncSession, prompt_type: str) -> Optional[PromptModel]:
        """根據 code 獲取 Prompt"""
        result = await session.execute(
            select(PromptModel).where(PromptModel.prompt_type == prompt_type)
        )
        return result.scalar_one_or_none()
    
    async def update(
        self,
        session: AsyncSession,
        id: int,
        prompt_type: Optional[str] = None,
        prompt: Optional[str] = None,
        retry_prompt: Optional[str] = None
    ) -> Optional[PromptModel]:
        """更新 Prompt"""
        result = await session.execute(
            select(PromptModel).where(PromptModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return None
        
        if prompt_type is not None:
            existing.prompt_type = prompt_type
        if prompt is not None:
            existing.prompt = prompt
        if retry_prompt is not None:
            existing.retry_prompt = retry_prompt
        
        await session.flush()
        await session.refresh(existing)
        return existing
    
    async def delete(self, session: AsyncSession, id: int) -> bool:
        """刪除 Prompt"""
        result = await session.execute(
            select(PromptModel).where(PromptModel.id == id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            return False
        
        await session.delete(existing)
        await session.flush()
        return True