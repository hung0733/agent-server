from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.models import SessionModel


class SessionDAO:
    """Session Data Access Object"""

    async def create(
        self,
        session: AsyncSession,
        agent_id: int,
        session_id: str,
        name: str = "未命名對話",
    ) -> SessionModel:
        """創建 Session (agent_id 是 DB ID，session_id 是 unique identifier)"""
        new_session = SessionModel(agent_id=agent_id, session_id=session_id, name=name)
        session.add(new_session)
        await session.flush()
        await session.refresh(new_session)
        return new_session

    async def make_sure_exist(
        self, session: AsyncSession, agent_db_id: int, session_id: str
    ):
        if not await self.exists_by_session_id(session, session_id):
            print(f"Create Seesion: {agent_db_id} {session_id}")
            await self.create(session, agent_db_id, session_id, session_id)
            await session.commit()

    async def exists_by_session_id(
        self, session: AsyncSession, session_id: str
    ) -> bool:
        """檢查 session_id 是否已存在"""
        result = await session.execute(
            select(SessionModel).where(SessionModel.session_id == session_id)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[SessionModel]:
        """根據 DB ID 獲取 Session"""
        result = await session.execute(
            select(SessionModel).where(SessionModel.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(
        self, session: AsyncSession, session_id: str
    ) -> Optional[SessionModel]:
        """根據 unique session_id 獲取 Session (非 default session)"""
        # 排除 "default" session，因為它需要配合 agent_id 查找
        if session_id == "default":
            return None

        result = await session.execute(
            select(SessionModel).where(SessionModel.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_default_session(
        self, session: AsyncSession, agent_db_id: int
    ) -> Optional[SessionModel]:
        """獲取 Agent 的 default session (agent_id + "default")"""
        result = await session.execute(
            select(SessionModel).where(
                SessionModel.agent_id == agent_db_id,
                SessionModel.session_id == "default",
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(
        self, session: AsyncSession, agent_db_id: int
    ) -> List[SessionModel]:
        """列出指定 Agent 的所有 Sessions"""
        result = await session.execute(
            select(SessionModel).where(SessionModel.agent_id == agent_db_id)
        )
        return result.scalars().all()

    async def update(
        self, session: AsyncSession, id: int, name: Optional[str] = None
    ) -> SessionModel:
        """更新 Session (根據 DB ID)"""
        sesh = await self.get_by_id(session, id)
        if not sesh:
            raise ValueError(f"Session with id {id} not found")

        if name is not None:
            sesh.name = name

        await session.flush()
        await session.refresh(sesh)
        return sesh

    async def delete_by_session_id(
        self, session: AsyncSession, agent_db_id: int | None, session_id: str
    ) -> bool:
        """刪除 Session，級聯刪除相關 Messages"""
        if session_id == "default" and agent_db_id is None:
            raise ValueError("Cannot delete default session without agent_db_id")

        if session_id == "default" and agent_db_id is not None:
            sesh = await self.get_default_session(session, agent_db_id)
        else:
            sesh = await self.get_by_session_id(session, session_id)

        if not sesh:
            return False

        await session.delete(sesh)
        await session.flush()
        return True
