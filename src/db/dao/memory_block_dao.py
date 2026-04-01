# pyright: reportMissingImports=false
"""
Data Access Object for MemoryBlock entity.

Import path: db.dao.memory_block_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.memory_block_dto import MemoryBlock, MemoryBlockCreate, MemoryBlockUpdate
from db.entity.memory_block_entity import MemoryBlock as MemoryBlockEntity


class MemoryBlockDAO:

    @staticmethod
    async def create(
        dto: MemoryBlockCreate,
        session: Optional[AsyncSession] = None,
    ) -> MemoryBlock:
        entity = MemoryBlockEntity(
            agent_instance_id=dto.agent_instance_id,
            memory_type=dto.memory_type,
            content=dto.content,
            version=dto.version,
            is_active=dto.is_active,
        )

        if session is not None:
            session.add(entity)
            await session.flush()
            await session.refresh(entity)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()

        return MemoryBlock.model_validate(entity)

    @staticmethod
    async def get_by_id(
        block_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[MemoryBlock]:
        async def _query(s: AsyncSession) -> Optional[MemoryBlockEntity]:
            result = await s.execute(
                select(MemoryBlockEntity).where(MemoryBlockEntity.id == block_id)
            )
            return result.scalar_one_or_none()

        if session is not None:
            entity = await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _query(s)
            await engine.dispose()

        return MemoryBlock.model_validate(entity) if entity else None

    @staticmethod
    async def get_by_agent_instance_id(
        agent_instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[MemoryBlock]:
        """Return all active memory blocks for an agent, newest first."""
        async def _query(s: AsyncSession) -> list[MemoryBlockEntity]:
            result = await s.execute(
                select(MemoryBlockEntity)
                .where(
                    MemoryBlockEntity.agent_instance_id == agent_instance_id,
                    MemoryBlockEntity.is_active.is_(True),
                )
                .order_by(MemoryBlockEntity.created_at.desc())
            )
            return list(result.scalars().all())

        if session is not None:
            entities = await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()

        return [MemoryBlock.model_validate(e) for e in entities]

    @staticmethod
    async def update(
        dto: MemoryBlockUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[MemoryBlock]:
        async def _update(s: AsyncSession, flush_only: bool = False) -> Optional[MemoryBlockEntity]:
            entity = await s.get(MemoryBlockEntity, dto.id)
            if entity is None:
                return None
            for field, value in dto.model_dump(exclude_unset=True, exclude={"id"}).items():
                if hasattr(entity, field):
                    setattr(entity, field, value)
            if flush_only:
                await s.flush()
            else:
                await s.commit()
            await s.refresh(entity)
            return entity

        if session is not None:
            entity = await _update(session, flush_only=True)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _update(s)
            await engine.dispose()

        return MemoryBlock.model_validate(entity) if entity else None

    @staticmethod
    async def delete(
        block_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        async def _delete(s: AsyncSession) -> bool:
            result = await s.execute(
                delete(MemoryBlockEntity).where(MemoryBlockEntity.id == block_id)
            )
            await s.commit()
            return result.rowcount > 0

        if session is not None:
            return await _delete(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                success = await _delete(s)
            await engine.dispose()
            return success
