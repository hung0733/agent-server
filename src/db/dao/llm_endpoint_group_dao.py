# pyright: reportMissingImports=false
"""
Data Access Object for LLMEndpointGroup entity operations.

This module provides static methods for CRUD operations on LLMEndpointGroup entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.llm_endpoint_group_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.llm_endpoint_dto import (
    LLMEndpointGroupCreate, LLMEndpointGroup, LLMEndpointGroupUpdate
)
from db.entity.llm_endpoint_entity import LLMEndpointGroup as LLMEndpointGroupEntity


class LLMEndpointGroupDAO:
    """Data Access Object for LLMEndpointGroup database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a group
        group_dto = await LLMEndpointGroupDAO.create(LLMEndpointGroupCreate(...))
        
        # Get group by ID
        group = await LLMEndpointGroupDAO.get_by_id(group_id)
        
        # Get groups by user ID
        groups = await LLMEndpointGroupDAO.get_by_user_id(user_id)
        
        # Get default group for user
        default = await LLMEndpointGroupDAO.get_default_group(user_id)
        
        # Update group
        updated = await LLMEndpointGroupDAO.update(LLMEndpointGroupUpdate(id=group_id, ...))
        
        # Delete group
        success = await LLMEndpointGroupDAO.delete(group_id)
    """
    
    @staticmethod
    async def create(
        dto: LLMEndpointGroupCreate,
        session: Optional[AsyncSession] = None,
    ) -> LLMEndpointGroup:
        """Create a new LLM endpoint group.
        
        Args:
            dto: LLMEndpointGroupCreate DTO with group data.
            session: Optional async session for transaction control.
            
        Returns:
            LLMEndpointGroup DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If unique constraint violated (duplicate name per user).
        """
        entity = LLMEndpointGroupEntity(
            user_id=dto.user_id,
            name=dto.name,
            description=dto.description,
            is_default=dto.is_default,
        )
        
        if session is not None:
            session.add(entity)
            await session.commit()
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
        
        return LLMEndpointGroup.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        group_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMEndpointGroup]:
        """Retrieve an LLM endpoint group by ID.
        
        Args:
            group_id: UUID of the group to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            LLMEndpointGroup DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[LLMEndpointGroupEntity]:
            result = await s.execute(
                select(LLMEndpointGroupEntity).where(LLMEndpointGroupEntity.id == group_id)
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
        
        if entity is None:
            return None
        return LLMEndpointGroup.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMEndpointGroup]:
        """Retrieve all LLM endpoint groups for a user.
        
        Args:
            user_id: UUID of the user.
            session: Optional async session for transaction control.
            
        Returns:
            List of LLMEndpointGroup DTOs.
        """
        async def _query(s: AsyncSession) -> List[LLMEndpointGroupEntity]:
            result = await s.execute(
                select(LLMEndpointGroupEntity).where(LLMEndpointGroupEntity.user_id == user_id)
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
        
        return [LLMEndpointGroup.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_default_group(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMEndpointGroup]:
        """Retrieve the default LLM endpoint group for a user.
        
        Args:
            user_id: UUID of the user.
            session: Optional async session for transaction control.
            
        Returns:
            LLMEndpointGroup DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[LLMEndpointGroupEntity]:
            result = await s.execute(
                select(LLMEndpointGroupEntity).where(
                    LLMEndpointGroupEntity.user_id == user_id,
                    LLMEndpointGroupEntity.is_default == True,
                )
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
        
        if entity is None:
            return None
        return LLMEndpointGroup.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMEndpointGroup]:
        """Retrieve all LLM endpoint groups with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of LLMEndpointGroup DTOs.
        """
        async def _query(s: AsyncSession) -> List[LLMEndpointGroupEntity]:
            result = await s.execute(
                select(LLMEndpointGroupEntity).limit(limit).offset(offset)
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
        
        return [LLMEndpointGroup.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: LLMEndpointGroupUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMEndpointGroup]:
        """Update an existing LLM endpoint group.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: LLMEndpointGroupUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated LLMEndpointGroup DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[LLMEndpointGroupEntity]:
            entity = await s.get(LLMEndpointGroupEntity, dto.id)
            if entity is None:
                return None
            
            update_data = dto.model_dump(exclude_unset=True, exclude={'id'})
            for field, value in update_data.items():
                if hasattr(entity, field):
                    setattr(entity, field, value)
            
            await s.commit()
            await s.refresh(entity)
            return entity
        
        if session is not None:
            entity = await _update(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _update(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return LLMEndpointGroup.model_validate(entity)
    
    @staticmethod
    async def delete(
        group_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an LLM endpoint group by ID.
        
        Note: Cascade delete will also remove all associated level endpoint assignments.
        
        Args:
            group_id: UUID of the group to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(LLMEndpointGroupEntity).where(LLMEndpointGroupEntity.id == group_id)
            result = await s.execute(stmt)
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
    
    @staticmethod
    async def exists(
        group_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an LLM endpoint group exists.
        
        Args:
            group_id: UUID of the group to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if group exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(LLMEndpointGroupEntity.id).where(LLMEndpointGroupEntity.id == group_id)
            )
            return result.scalar() is not None
        
        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                exists = await _query(s)
            await engine.dispose()
            return exists
    
    @staticmethod
    async def count(
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count total number of LLM endpoint groups.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of LLM endpoint groups in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(LLMEndpointGroupEntity)
            )
            return result.scalar() or 0
        
        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count