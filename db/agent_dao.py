from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.models import AgentModel


class AgentDAO:
    """Agent Data Access Object"""
    
    async def create(
        self, 
        session: AsyncSession, 
        agent_id: str, 
        name: str, 
        sys_prompt: Optional[str] = None
    ) -> AgentModel:
        """創建 Agent (返回 AgentModel)"""
        new_agent = AgentModel(
            agent_id=agent_id,
            name=name,
            sys_prompt=sys_prompt
        )
        session.add(new_agent)
        await session.flush()  # Get the generated id
        await session.refresh(new_agent)
        return new_agent
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[AgentModel]:
        """根據 DB ID 獲取 Agent"""
        result = await session.execute(select(AgentModel).where(AgentModel.id == id))
        return result.scalar_one_or_none()
    
    async def get_by_agent_id(self, session: AsyncSession, agent_id: str) -> Optional[AgentModel]:
        """根據 unique agent_id 獲取 Agent"""
        result = await session.execute(
            select(AgentModel).where(AgentModel.agent_id == agent_id)
        )
        return result.scalar_one_or_none()
    
    async def list_all(self, session: AsyncSession) -> List[AgentModel]:
        """列出所有 Agents"""
        result = await session.execute(select(AgentModel))
        return result.scalars().all()
    
    async def update(
        self, 
        session: AsyncSession, 
        id: int, 
        name: Optional[str] = None, 
        sys_prompt: Optional[str] = None
    ) -> AgentModel:
        """更新 Agent (根據 DB ID)"""
        agent = await self.get_by_id(session, id)
        if not agent:
            raise ValueError(f"Agent with id {id} not found")
        
        if name is not None:
            agent.name = name
        if sys_prompt is not None:
            agent.sys_prompt = sys_prompt
        
        await session.flush()
        await session.refresh(agent)
        return agent
    
    async def delete_by_agent_id(self, session: AsyncSession, agent_id: str) -> bool:
        """刪除 Agent (根據 unique agent_id)，級聯刪除相關 Session 和 Messages"""
        agent = await self.get_by_agent_id(session, agent_id)
        if not agent:
            return False
        
        await session.delete(agent)
        await session.flush()
        return True