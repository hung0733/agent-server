import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from db.conn_pool import get_db
from db.models import SessionModel, AgentModel
from db.session_dao import SessionDAO
from schemas.session import SessionCreate, SessionUpdate, SessionOut

router = APIRouter(prefix="/v1/sessions", tags=["Sessions"])


@router.get("/", response_model=List[SessionOut])
async def list_sessions(
    agent_id: Optional[str] = Query(None, description="Filter by agent's unique identifier"),
    db: AsyncSession = Depends(get_db)
):
    """列出所有 Sessions (可選按 agent_id 過濾)"""
    session_dao = SessionDAO()
    
    if agent_id:
        # 根據 agent_id 查找該 Agent 的所有 sessions
        result = await db.execute(
            select(AgentModel).where(AgentModel.agent_id == agent_id)
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        
        sessions = await session_dao.list_by_agent(db, agent.id)
    else:
        # 列出所有 sessions
        result = await db.execute(select(SessionModel))
        sessions = result.scalars().all()
    
    return [SessionOut.from_model(s) for s in sessions]


@router.post("/", response_model=SessionOut)
async def create_session(
    data: SessionCreate,
    db: AsyncSession = Depends(get_db)
):
    """創建新 Session (session_id 自動生成)"""
    import uuid
    
    session_dao = SessionDAO()
    
    # 檢查 Agent 是否存在
    agent_result = await db.execute(
        select(AgentModel).where(AgentModel.agent_id == data.agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{data.agent_id}' not found")
    
    # 自動生成 session_id (格式：session-{uuid})，確保唯一性
    generated_session_id = f"session-{uuid.uuid4().hex[:8]}"
    
    # 檢查生成的 session_id 是否已存在，如果存在則重新生成
    while await session_dao.exists_by_session_id(db, generated_session_id):
        generated_session_id = f"session-{uuid.uuid4().hex[:8]}"
    
    # 創建 Session
    new_session = await session_dao.create(
        db,
        agent_id=agent.id,
        session_id=generated_session_id,
        name=data.name
    )
    
    return SessionOut.from_model(new_session)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """獲取 Session 詳情 (非 default session)"""
    # 排除 "default" session，因為它需要配合 agent_id 查找
    if session_id == "default":
        raise HTTPException(
            status_code=400, 
            detail="Use /agents/{agent_id}/sessions/default to access the default session"
        )
    
    session_dao = SessionDAO()
    sesh = await session_dao.get_by_session_id(db, session_id)
    
    if not sesh:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    return SessionOut.from_model(sesh)


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新 Session 信息 (非 default session)"""
    # 排除 "default" session
    if session_id == "default":
        raise HTTPException(
            status_code=400, 
            detail="Default session cannot be updated directly. Use Agent API instead."
        )
    
    session_dao = SessionDAO()
    sesh = await session_dao.get_by_session_id(db, session_id)
    
    if not sesh:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    updated_sesh = await session_dao.update(db, sesh.id, name=data.name)
    return SessionOut.from_model(updated_sesh)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """刪除 Session (非 default session)"""
    # 排除 "default" session
    if session_id == "default":
        raise HTTPException(
            status_code=400, 
            detail="Default session cannot be deleted directly. Use Agent API instead."
        )
    
    session_dao = SessionDAO()
    success = await session_dao.delete_by_session_id(db, None, session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    return {"message": f"Session '{session_id}' deleted successfully"}


@router.get("/agents/{agent_id}/sessions/default", response_model=SessionOut)
async def get_default_session(
    agent_id: str,
    db: AsyncSession = Depends(get_db)
):
    """獲取 Agent 的 default session"""
    session_dao = SessionDAO()
    
    # 查找 Agent
    agent_result = await db.execute(
        select(AgentModel).where(AgentModel.agent_id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    # 查找 default session
    sesh = await session_dao.get_default_session(db, agent.id)
    
    if not sesh:
        raise HTTPException(status_code=404, detail=f"Default session for Agent '{agent_id}' not found")
    
    return SessionOut.from_model(sesh)


@router.patch("/agents/{agent_id}/sessions/default", response_model=SessionOut)
async def update_default_session(
    agent_id: str,
    data: SessionUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新 Agent 的 default session"""
    session_dao = SessionDAO()
    
    # 查找 Agent
    agent_result = await db.execute(
        select(AgentModel).where(AgentModel.agent_id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    # 查找 default session
    sesh = await session_dao.get_default_session(db, agent.id)
    
    if not sesh:
        raise HTTPException(status_code=404, detail=f"Default session for Agent '{agent_id}' not found")
    
    updated_sesh = await session_dao.update(db, sesh.id, name=data.name)
    return SessionOut.from_model(updated_sesh)


@router.delete("/agents/{agent_id}/sessions/default")
async def delete_default_session(
    agent_id: str,
    db: AsyncSession = Depends(get_db)
):
    """刪除 Agent 的 default session"""
    session_dao = SessionDAO()
    
    # 查找 Agent
    agent_result = await db.execute(
        select(AgentModel).where(AgentModel.agent_id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    success = await session_dao.delete_by_session_id(db, agent.id, "default")
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Default session for Agent '{agent_id}' not found")
    
    return {"message": f"Default session for Agent '{agent_id}' deleted successfully"}