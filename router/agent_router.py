from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from db.models import AgentModel
from db.conn_pool import get_db
from schemas.agent import AgentCreate, AgentUpdate, AgentOut

router = APIRouter(prefix="/v1/agents", tags=["Agents"])

# 1. List all agents
@router.get("/", response_model=List[AgentOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel))
    return result.scalars().all()

# 2. Create agent
@router.post("/", response_model=AgentOut)
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    # 檢查 agent_id 係咪已經存在
    existing = await db.execute(select(AgentModel).where(AgentModel.agent_id == data.agent_id))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Agent ID already exists")
    
    new_agent = AgentModel(**data.model_dump())
    db.add(new_agent)
    await db.commit()
    await db.refresh(new_agent)
    return new_agent

# 3. Retrieve agent info
@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel).where(AgentModel.agent_id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

# 4. Update agent info
@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel).where(AgentModel.agent_id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(agent, key, value)
    
    await db.commit()
    await db.refresh(agent)
    return agent

# 5. Delete agent info
@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel).where(AgentModel.agent_id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    await db.delete(agent)
    await db.commit()
    return {"message": f"Agent {agent_id} deleted successfully"}