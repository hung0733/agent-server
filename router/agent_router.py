import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from db.models import AgentModel, SessionModel
from db.conn_pool import get_db
from db.agent_dao import AgentDAO
from schemas.agent import AgentCreate, AgentUpdate, AgentOut

router = APIRouter(prefix="/v1/agents", tags=["Agents"])


# 1. List all agents
@router.get("/", response_model=List[AgentOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    """列出所有 Agents"""
    agent_dao = AgentDAO()
    agents = await agent_dao.list_all(db)
    return [AgentOut.from_model(a) for a in agents]


# 2. Create agent
@router.post("/", response_model=AgentOut)
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    """創建新 Agent (自動創建 default session)"""
    agent_dao = AgentDAO()
    
    # 檢查 name 有無重複
    existing = await db.execute(select(AgentModel).where(AgentModel.name == data.name))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Agent Name already exists")

    try:
        # 建立新 Agent
        new_agent = await agent_dao.create(
            db, 
            agent_id=f"agent-{uuid.uuid4()}", 
            name=data.name, 
            sys_prompt=data.sys_prompt
        )
        
        # 建立預設 Session
        from db.session_dao import SessionDAO
        session_dao = SessionDAO()
        await session_dao.create(
            db, 
            agent_id=new_agent.id, 
            session_id="default", 
            name="預設對話"
        )

        return AgentOut.from_model(new_agent)

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"建立失敗：{str(e)}")


# 3. Retrieve agent info
@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """獲取 Agent 詳情"""
    agent_dao = AgentDAO()
    agent = await agent_dao.get_by_agent_id(db, agent_id)
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return AgentOut.from_model(agent)


# 4. Update agent info
@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    """更新 Agent 信息"""
    agent_dao = AgentDAO()
    
    # 獲取 agent (根據 unique agent_id)
    agent_result = await db.execute(select(AgentModel).where(AgentModel.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # 更新數據
    update_data = data.model_dump(exclude_unset=True)
    updated_agent = await agent_dao.update(db, agent.id, **update_data)
    
    return AgentOut.from_model(updated_agent)


# 5. Delete agent info
@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """刪除 Agent (級聯刪除相關 Session 和 Messages)"""
    agent_dao = AgentDAO()
    success = await agent_dao.delete_by_agent_id(db, agent_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {"message": f"Agent {agent_id} deleted successfully"}


# 輔助方法：從 AgentModel 創建 AgentOut
class AgentOut:
    @classmethod
    def from_model(cls, a: AgentModel) -> 'AgentOut':
        """從 Model 轉換為 Out schema"""
        return cls(
            id=a.id,
            agent_id=a.agent_id,
            name=a.name,
            sys_prompt=a.sys_prompt
        )