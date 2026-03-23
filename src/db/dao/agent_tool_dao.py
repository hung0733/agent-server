# pyright: reportMissingImports=false
"""
Data Access Objects for agent–tool associations.

AgentTypeToolDAO   — manages agent_type_tools (type-level tool grants)
AgentInstanceToolDAO — manages agent_instance_tools (instance-level overrides)
                       and provides get_effective_tools() which merges both layers.
"""
from __future__ import annotations

from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.agent_tool_dto import (
    AgentInstanceTool,
    AgentInstanceToolCreate,
    AgentInstanceToolUpdate,
    AgentTypeTool,
    AgentTypeToolCreate,
    AgentTypeToolUpdate,
)
from db.entity.agent_tool_entity import (
    AgentInstanceTool as AgentInstanceToolEntity,
    AgentTypeTool as AgentTypeToolEntity,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_session():
    """Create a throw-away engine + session factory."""
    from db import create_engine, AsyncSession as _AS, async_sessionmaker
    engine = create_engine()
    factory = async_sessionmaker(engine, class_=_AS, expire_on_commit=False)
    return engine, factory


# ─────────────────────────────────────────────────────────────────────────────
# AgentTypeToolDAO
# ─────────────────────────────────────────────────────────────────────────────

class AgentTypeToolDAO:
    """CRUD for agent_type_tools.

    Example:
        # Assign tool to agent type
        record = await AgentTypeToolDAO.assign(
            AgentTypeToolCreate(agent_type_id=type_id, tool_id=tool_id)
        )

        # List tools for a type
        records = await AgentTypeToolDAO.get_tools_for_type(type_id)

        # Revoke
        await AgentTypeToolDAO.revoke(type_id, tool_id)
    """

    @staticmethod
    async def assign(
        dto: AgentTypeToolCreate,
        session: Optional[AsyncSession] = None,
    ) -> AgentTypeTool:
        """Create a new agent type → tool association."""
        entity = AgentTypeToolEntity(
            agent_type_id=dto.agent_type_id,
            tool_id=dto.tool_id,
            is_active=dto.is_active,
        )

        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()

        return AgentTypeTool.model_validate(entity)

    @staticmethod
    async def revoke(
        agent_type_id: UUID,
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete the association between an agent type and a tool.

        Returns True if a record was deleted, False if it did not exist.
        """
        async def _delete(s: AsyncSession) -> bool:
            result = await s.execute(
                delete(AgentTypeToolEntity).where(
                    AgentTypeToolEntity.agent_type_id == agent_type_id,
                    AgentTypeToolEntity.tool_id == tool_id,
                )
            )
            await s.commit()
            return result.rowcount > 0

        if session is not None:
            return await _delete(session)
        engine, factory = _make_session()
        async with factory() as s:
            deleted = await _delete(s)
        await engine.dispose()
        return deleted

    @staticmethod
    async def get_tools_for_type(
        agent_type_id: UUID,
        active_only: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentTypeTool]:
        """Return all tool associations for an agent type."""
        async def _query(s: AsyncSession) -> list[AgentTypeToolEntity]:
            stmt = select(AgentTypeToolEntity).where(
                AgentTypeToolEntity.agent_type_id == agent_type_id
            )
            if active_only:
                stmt = stmt.where(AgentTypeToolEntity.is_active == True)
            result = await s.execute(stmt)
            return list(result.scalars().all())

        if session is not None:
            entities = await _query(session)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                entities = await _query(s)
            await engine.dispose()

        return [AgentTypeTool.model_validate(e) for e in entities]

    @staticmethod
    async def get_types_for_tool(
        tool_id: UUID,
        active_only: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentTypeTool]:
        """Return all agent type associations for a given tool (reverse lookup)."""
        async def _query(s: AsyncSession) -> list[AgentTypeToolEntity]:
            stmt = select(AgentTypeToolEntity).where(
                AgentTypeToolEntity.tool_id == tool_id
            )
            if active_only:
                stmt = stmt.where(AgentTypeToolEntity.is_active == True)
            result = await s.execute(stmt)
            return list(result.scalars().all())

        if session is not None:
            entities = await _query(session)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                entities = await _query(s)
            await engine.dispose()

        return [AgentTypeTool.model_validate(e) for e in entities]

    @staticmethod
    async def is_assigned(
        agent_type_id: UUID,
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Return True if the tool is associated with the agent type."""
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(AgentTypeToolEntity.id).where(
                    AgentTypeToolEntity.agent_type_id == agent_type_id,
                    AgentTypeToolEntity.tool_id == tool_id,
                )
            )
            return result.scalar() is not None

        if session is not None:
            return await _query(session)
        engine, factory = _make_session()
        async with factory() as s:
            found = await _query(s)
        await engine.dispose()
        return found

    @staticmethod
    async def update(
        dto: AgentTypeToolUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentTypeTool]:
        """Update is_active on an agent_type_tools record."""
        async def _update(s: AsyncSession) -> Optional[AgentTypeToolEntity]:
            entity = await s.get(AgentTypeToolEntity, dto.id)
            if entity is None:
                return None
            for field, value in dto.model_dump(exclude_unset=True, exclude={"id"}).items():
                if hasattr(entity, field):
                    setattr(entity, field, value)
            await s.commit()
            await s.refresh(entity)
            return entity

        if session is not None:
            entity = await _update(session)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                entity = await _update(s)
            await engine.dispose()

        return AgentTypeTool.model_validate(entity) if entity else None


# ─────────────────────────────────────────────────────────────────────────────
# AgentInstanceToolDAO
# ─────────────────────────────────────────────────────────────────────────────

class AgentInstanceToolDAO:
    """CRUD for agent_instance_tools, plus effective tool resolution.

    Example:
        # Add an extra tool for a specific instance
        record = await AgentInstanceToolDAO.assign(
            AgentInstanceToolCreate(agent_instance_id=inst_id, tool_id=tool_id)
        )

        # Disable a type-level tool for this instance
        record = await AgentInstanceToolDAO.assign(
            AgentInstanceToolCreate(
                agent_instance_id=inst_id, tool_id=tool_id, is_enabled=False
            )
        )

        # Get effective (merged) tool IDs
        tool_ids = await AgentInstanceToolDAO.get_effective_tools(inst_id)
    """

    @staticmethod
    async def assign(
        dto: AgentInstanceToolCreate,
        session: Optional[AsyncSession] = None,
    ) -> AgentInstanceTool:
        """Create or update an instance-level tool override."""
        entity = AgentInstanceToolEntity(
            agent_instance_id=dto.agent_instance_id,
            tool_id=dto.tool_id,
            is_enabled=dto.is_enabled,
            config_override=dto.config_override,
        )

        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()

        return AgentInstanceTool.model_validate(entity)

    @staticmethod
    async def revoke(
        agent_instance_id: UUID,
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an instance-level tool override record."""
        async def _delete(s: AsyncSession) -> bool:
            result = await s.execute(
                delete(AgentInstanceToolEntity).where(
                    AgentInstanceToolEntity.agent_instance_id == agent_instance_id,
                    AgentInstanceToolEntity.tool_id == tool_id,
                )
            )
            await s.commit()
            return result.rowcount > 0

        if session is not None:
            return await _delete(session)
        engine, factory = _make_session()
        async with factory() as s:
            deleted = await _delete(s)
        await engine.dispose()
        return deleted

    @staticmethod
    async def get_overrides_for_instance(
        agent_instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentInstanceTool]:
        """Return all instance-level override records for an agent instance."""
        async def _query(s: AsyncSession) -> list[AgentInstanceToolEntity]:
            result = await s.execute(
                select(AgentInstanceToolEntity).where(
                    AgentInstanceToolEntity.agent_instance_id == agent_instance_id
                )
            )
            return list(result.scalars().all())

        if session is not None:
            entities = await _query(session)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                entities = await _query(s)
            await engine.dispose()

        return [AgentInstanceTool.model_validate(e) for e in entities]

    @staticmethod
    async def get_effective_tools(
        agent_instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[UUID]:
        """Return the effective list of tool IDs available to this agent instance.

        Merges two layers:
        1. Type-level tools (from agent_type_tools via the instance's agent_type_id)
        2. Instance-level overrides (agent_instance_tools)

        Rules:
        - Type-level active tools are included by default.
        - Instance override with is_enabled=True adds the tool (even if not in type set).
        - Instance override with is_enabled=False removes the tool from the result.
        """
        from db.entity.agent_entity import AgentInstance as AgentInstanceEntity

        async def _resolve(s: AsyncSession) -> List[UUID]:
            # 1. Fetch instance to get agent_type_id
            instance = await s.get(AgentInstanceEntity, agent_instance_id)
            if instance is None:
                return []

            # 2. Type-level active tool IDs
            type_result = await s.execute(
                select(AgentTypeToolEntity.tool_id).where(
                    AgentTypeToolEntity.agent_type_id == instance.agent_type_id,
                    AgentTypeToolEntity.is_active == True,
                )
            )
            type_tool_ids: Set[UUID] = set(type_result.scalars().all())

            # 3. Instance-level overrides
            inst_result = await s.execute(
                select(AgentInstanceToolEntity).where(
                    AgentInstanceToolEntity.agent_instance_id == agent_instance_id
                )
            )
            overrides: list[AgentInstanceToolEntity] = list(inst_result.scalars().all())

            # 4. Merge
            effective: Set[UUID] = set(type_tool_ids)
            for override in overrides:
                if override.is_enabled:
                    effective.add(override.tool_id)
                else:
                    effective.discard(override.tool_id)

            return list(effective)

        if session is not None:
            return await _resolve(session)
        engine, factory = _make_session()
        async with factory() as s:
            result = await _resolve(s)
        await engine.dispose()
        return result

    @staticmethod
    async def update(
        dto: AgentInstanceToolUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentInstanceTool]:
        """Update is_enabled and/or config_override on an instance tool record."""
        async def _update(s: AsyncSession) -> Optional[AgentInstanceToolEntity]:
            entity = await s.get(AgentInstanceToolEntity, dto.id)
            if entity is None:
                return None
            for field, value in dto.model_dump(exclude_unset=True, exclude={"id"}).items():
                if hasattr(entity, field):
                    setattr(entity, field, value)
            await s.commit()
            await s.refresh(entity)
            return entity

        if session is not None:
            entity = await _update(session)
        else:
            engine, factory = _make_session()
            async with factory() as s:
                entity = await _update(s)
            await engine.dispose()

        return AgentInstanceTool.model_validate(entity) if entity else None
