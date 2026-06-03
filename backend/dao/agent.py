from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.dao.agent_type import AgentTypeDAO
from backend.entities.agent import Agent


class AgentDAO(BaseDAO[Agent]):
    model = Agent

    async def create(self, data: BaseModel | dict[str, Any]) -> Agent:
        values, agent_type = await self._resolve_agent_type(self._to_dict(data))
        item = Agent(**values)
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        if agent_type is not None:
            item.agent_type_ref = agent_type
        return item

    async def update(self, item: Agent, data: BaseModel | dict[str, Any]) -> Agent:
        values, agent_type = await self._resolve_agent_type(
            self._to_dict(data, exclude_unset=True)
        )
        for key, value in values.items():
            setattr(item, key, value)
        await self.session.flush()
        await self.session.refresh(item)
        if agent_type is not None:
            item.agent_type_ref = agent_type
        return item

    async def get_by_agent_id(self, agent_id: str) -> Agent | None:
        stmt = select(Agent).where(Agent.agent_id == agent_id)
        return await self.session.scalar(stmt)

    async def list_by_user_id(self, user_id: int) -> list[Agent]:
        stmt = select(Agent).where(Agent.user_id == user_id)
        result = await self.session.scalars(stmt)
        return list(result)

    async def get_first_active_sub_agent_by_user_and_type(
        self, *, user_id: int, agent_type_id: int
    ) -> Agent | None:
        stmt = (
            select(Agent)
            .where(
                Agent.user_id == user_id,
                Agent.agent_type_id == agent_type_id,
                Agent.is_active.is_(True),
                Agent.is_sub_agent.is_(True),
            )
            .order_by(Agent.id.asc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def _resolve_agent_type(self, values: dict[str, Any]) -> tuple[dict[str, Any], Any | None]:
        code = values.pop("agent_type", None)
        agent_type = None
        if values.get("agent_type_id") is None and code:
            agent_type = await AgentTypeDAO(self.session).get_or_create_by_code(
                str(code)
            )
            values["agent_type_id"] = agent_type.id
        return values, agent_type
