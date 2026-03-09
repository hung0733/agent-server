import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
from typing import List, Optional

from db.conn_pool import get_db
from db.models import MessageModel, SessionModel, AgentModel
from db.message_dao import MessageDAO
from dto.message import MessageDTO
from schemas.message import MessageCreate, MessageOut

router = APIRouter(prefix="/v1/sessions/messages", tags=["Messages"])


@router.get("/", response_model=List[MessageOut])
async def list_messages(
    agent_id: Optional[str] = Query(None, description="Filter by agent's unique identifier (finds default session messages)"),
    session_id: Optional[str] = Query(None, description="Filter by session's unique identifier"),
    limit: Optional[int] = Query(100, ge=1, le=1000, description="Maximum number of messages to return"),
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
    db: AsyncSession = Depends(get_db)
):
    """列出 Messages (可選按 agent_id 或 session_id 過濾)"""
    message_dao = MessageDAO()
    
    if agent_id and not session_id:
        # 根據 agent_id 查找 default session 的 messages
        agent_result = await db.execute(
            select(AgentModel).where(AgentModel.agent_id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        
        # 查找 default session
        session_result = await db.execute(
            select(SessionModel).where(
                SessionModel.agent_id == agent.id,
                SessionModel.session_id == "default"
            )
        )
        sesh = session_result.scalar_one_or_none()
        
        if not sesh:
            raise HTTPException(status_code=404, detail=f"Default session for Agent '{agent_id}' not found")
        
        messages = await message_dao.list_by_session(db, sesh.id, limit=limit, offset=offset)
    
    elif session_id and not agent_id:
        # 根據 session_id 查找 messages
        if session_id == "default":
            raise HTTPException(
                status_code=400, 
                detail="Use agent_id instead of session_id='default' to get default session messages"
            )
        
        sesh_result = await db.execute(
            select(SessionModel).where(SessionModel.session_id == session_id)
        )
        sesh = sesh_result.scalar_one_or_none()
        
        if not sesh:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        
        messages = await message_dao.list_by_session(db, sesh.id, limit=limit, offset=offset)
    
    else:
        # 列出所有 messages (不建議，僅用於調試)
        if agent_id and session_id:
            raise HTTPException(
                status_code=400, 
                detail="Cannot specify both agent_id and session_id"
            )
        
        messages = await message_dao.list_all(db)
    
    return [MessageOut.from_model(m) for m in messages]


@router.post("/", response_model=MessageOut)
async def create_message(
    data: MessageCreate,
    db: AsyncSession = Depends(get_db)
):
    """創建新 Message"""
    message_dao = MessageDAO()
    
    # 查找 Session
    if data.session_id == "default":
        raise HTTPException(
            status_code=400, 
            detail="Use agent_id instead of session_id='default' to create messages"
        )
    
    sesh_result = await db.execute(
        select(SessionModel).where(SessionModel.session_id == data.session_id)
    )
    sesh = sesh_result.scalar_one_or_none()
    
    if not sesh:
        raise HTTPException(status_code=404, detail=f"Session '{data.session_id}' not found")
    
    # 查找 Agent (獲取 agent_id)
    agent_result = await db.execute(
        select(AgentModel).where(AgentModel.id == sesh.agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent for session not found")
    
    # 創建 Message
    new_message = await message_dao.create(
        db,
        agent_id=agent.id,
        session_id=sesh.id,
        step_id=data.step_id or f"step-{uuid.uuid4()}",
        msg_id=f"msg-{uuid.uuid4()}",
        msg_type=data.msg_type,
        content=data.content,
        is_think_mode=data.is_think_mode,
        sent_by=data.sent_by,
        token=data.token,
        create_date=datetime.now()
    )
    
    return MessageOut.from_model(new_message)


@router.get("/{msg_id}", response_model=MessageOut)
async def get_message(
    msg_id: str,
    db: AsyncSession = Depends(get_db)
):
    """獲取 Message 詳情"""
    message_dao = MessageDAO()
    message = await message_dao.get_by_msg_id(db, msg_id)
    
    if not message:
        raise HTTPException(status_code=404, detail=f"Message '{msg_id}' not found")
    
    return MessageOut.from_model(message)


@router.delete("/{msg_id}")
async def delete_message(
    msg_id: str,
    db: AsyncSession = Depends(get_db)
):
    """刪除 Message"""
    message_dao = MessageDAO()
    success = await message_dao.delete_by_msg_id(db, msg_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Message '{msg_id}' not found")
    
    return {"message": f"Message '{msg_id}' deleted successfully"}


# 輔助方法：從 MessageModel 創建 MessageOut
class MessageOut:
    @classmethod
    def from_model(cls, m: MessageModel) -> 'MessageOut':
        """從 Model 轉換為 Out schema"""
        return cls(
            id=m.id,
            agent_id=m.agent_id,
            session_id=m.session_id,
            step_id=m.step_id,
            msg_id=m.msg_id,
            msg_type=m.msg_type,
            create_date=m.create_date,
            content=m.content,
            is_think_mode=m.is_think_mode,
            sent_by=m.sent_by,
            token=m.token
        )