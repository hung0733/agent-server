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

# 定義 session_id 的命名規範常量
SESSION_ID_PREFIX: str = "session-"


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


# 新增：自定義異常類 - 用於 session_id 格式錯誤
class InvalidSessionIDError(HTTPException):
    """Session ID 格式不正確的錯誤"""
    
    def __init__(self, session_id: str) -> None:
        super().__init__(
            status_code=400,
            detail={
                "error": "invalid_session_id",
                "message": f"Session ID '{session_id}' is not valid.",
                "hint": f"Session IDs must start with '{SESSION_ID_PREFIX}' prefix."
            }
        )


# 新增：驗證函數 - 檢查 session_id 是否以指定前綴開頭
def validate_session_id_format(session_id: str) -> None:
    """驗證 session_id 格式是否符合規範
    
    Args:
        session_id: 要驗證的 session ID
        
    Raises:
        InvalidSessionIDError: 如果 session_id 不以指定的前綴開頭
    """
    if not session_id.startswith(SESSION_ID_PREFIX):
        raise InvalidSessionIDError(session_id)


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新 Session 信息"""
    # 驗證 session_id 格式
    validate_session_id_format(session_id)
    
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
    """刪除 Session"""
    # 驗證 session_id 格式
    validate_session_id_format(session_id)
    
    session_dao = SessionDAO()
    success = await session_dao.delete_by_session_id(db, None, session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    return {"message": f"Session '{session_id}' deleted successfully"}


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """獲取 Session 詳情"""
    # 驗證 session_id 格式
    validate_session_id_format(session_id)
    
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
    """更新 Session 信息"""
    # 驗證 session_id 格式
    validate_session_id_format(session_id)
    
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
    """刪除 Session"""
    # 驗證 session_id 格式
    validate_session_id_format(session_id)
    
    session_dao = SessionDAO()
    success = await session_dao.delete_by_session_id(db, None, session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    return {"message": f"Session '{session_id}' deleted successfully"}