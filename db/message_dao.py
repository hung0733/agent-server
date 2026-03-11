from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime

from db.models import MessageModel


class MessageDAO:
    """Message Data Access Object"""
    
    async def create(
        self,
        session: AsyncSession,
        session_id: int,
        step_id: str,
        msg_id: str,
        msg_type: str,
        content: str,
        is_think_mode: bool = False,
        sent_by: str = "assistant",
        token: int = 0,
        create_date: Optional[datetime] = None
    ) -> MessageModel:
        """創建 Message"""
        new_message = MessageModel(
            session_id=session_id,
            step_id=step_id,
            msg_id=msg_id,
            msg_type=msg_type,
            content=content,
            is_think_mode=is_think_mode,
            sent_by=sent_by,
            token=token,
            create_date=create_date or datetime.now()
        )
        session.add(new_message)
        await session.flush()
        await session.refresh(new_message)
        return new_message
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[MessageModel]:
        """根據 DB ID 獲取 Message"""
        result = await session.execute(select(MessageModel).where(MessageModel.id == id))
        return result.scalar_one_or_none()
    
    async def get_by_msg_id(self, session: AsyncSession, msg_id: str) -> Optional[MessageModel]:
        """根據 unique msg_id 獲取 Message (可找到對應的 agent_id 和 session_id)"""
        result = await session.execute(
            select(MessageModel).where(MessageModel.msg_id == msg_id)
        )
        return result.scalar_one_or_none()
    
    async def list_all(self, session: AsyncSession) -> List[MessageModel]:
        """列出所有 Messages"""
        result = await session.execute(select(MessageModel))
        return result.scalars().all()
    
    async def list_by_session(
        self, 
        session: AsyncSession, 
        session_db_id: int,
        limit: Optional[int] = None, 
        offset: int = 0
    ) -> List[MessageModel]:
        """列出指定 Session 的所有 Messages (按 create_date 排序)"""
        query = select(MessageModel).where(
            MessageModel.session_id == session_db_id
        ).order_by(MessageModel.create_date.asc())
        
        if limit is not None:
            query = query.limit(limit).offset(offset)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def update(self, session: AsyncSession, id: int, **kwargs) -> MessageModel:
        """更新 Message (根據 DB ID)"""
        message = await self.get_by_id(session, id)
        if not message:
            raise ValueError(f"Message with id {id} not found")
        
        for key, value in kwargs.items():
            if hasattr(message, key):
                setattr(message, key, value)
        
        await session.flush()
        await session.refresh(message)
        return message
    
    async def delete_by_msg_id(self, session: AsyncSession, msg_id: str) -> bool:
        """刪除 Message (根據 unique msg_id)"""
        message = await self.get_by_msg_id(session, msg_id)
        if not message:
            return False
        
        await session.delete(message)
        await session.flush()
        return True
    
    async def delete_by_session(self, session: AsyncSession, session_db_id: int) -> bool:
        """刪除指定 Session 的所有 Messages"""
        messages = await self.list_by_session(session, session_db_id)
        if not messages:
            return False
        
        for message in messages:
            await session.delete(message)
        
        await session.flush()
        return True