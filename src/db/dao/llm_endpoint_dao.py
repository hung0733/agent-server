# pyright: reportMissingImports=false
"""
Data Access Object for LLMEndpoint entity operations.

This module provides static methods for CRUD operations on LLMEndpoint entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.llm_endpoint_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.llm_endpoint_dto import LLMEndpointCreate, LLMEndpoint, LLMEndpointUpdate
from db.entity.llm_endpoint_entity import LLMEndpoint as LLMEndpointEntity


class LLMEndpointDAO:
    """Data Access Object for LLMEndpoint database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create an endpoint
        endpoint_dto = await LLMEndpointDAO.create(LLMEndpointCreate(...))
        
        # Get endpoint by ID
        endpoint = await LLMEndpointDAO.get_by_id(endpoint_id)
        
        # Get endpoints by user ID
        endpoints = await LLMEndpointDAO.get_by_user_id(user_id)
        
        # Update endpoint
        updated = await LLMEndpointDAO.update(LLMEndpointUpdate(id=endpoint_id, ...))
        
        # Delete endpoint
        success = await LLMEndpointDAO.delete(endpoint_id)
    """
    
    @staticmethod
    async def create(
        dto: LLMEndpointCreate,
        session: Optional[AsyncSession] = None,
    ) -> LLMEndpoint:
        """Create a new LLM endpoint.
        
        Args:
            dto: LLMEndpointCreate DTO with endpoint data.
            session: Optional async session for transaction control.
            
        Returns:
            LLMEndpoint DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        entity = LLMEndpointEntity(
            user_id=dto.user_id,
            name=dto.name,
            base_url=dto.base_url,
            api_key_encrypted=dto.api_key_encrypted,
            model_name=dto.model_name,
            config_json=dto.config_json,
            is_active=dto.is_active,
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
        
        return LLMEndpoint.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMEndpoint]:
        """Retrieve an LLM endpoint by ID.
        
        Args:
            endpoint_id: UUID of the endpoint to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            LLMEndpoint DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[LLMEndpointEntity]:
            result = await s.execute(
                select(LLMEndpointEntity).where(LLMEndpointEntity.id == endpoint_id)
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
        return LLMEndpoint.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMEndpoint]:
        """Retrieve all LLM endpoints for a user.
        
        Args:
            user_id: UUID of the user.
            session: Optional async session for transaction control.
            
        Returns:
            List of LLMEndpoint DTOs.
        """
        async def _query(s: AsyncSession) -> List[LLMEndpointEntity]:
            result = await s.execute(
                select(LLMEndpointEntity).where(LLMEndpointEntity.user_id == user_id)
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
        
        return [LLMEndpoint.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        active_only: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMEndpoint]:
        """Retrieve all LLM endpoints with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            active_only: If True, only return active endpoints.
            session: Optional async session for transaction control.
            
        Returns:
            List of LLMEndpoint DTOs.
        """
        async def _query(s: AsyncSession) -> List[LLMEndpointEntity]:
            query = select(LLMEndpointEntity).limit(limit).offset(offset)
            if active_only:
                query = query.where(LLMEndpointEntity.is_active == True)
            result = await s.execute(query)
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
        
        return [LLMEndpoint.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: LLMEndpointUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMEndpoint]:
        """Update an existing LLM endpoint.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: LLMEndpointUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated LLMEndpoint DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[LLMEndpointEntity]:
            entity = await s.get(LLMEndpointEntity, dto.id)
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
        return LLMEndpoint.model_validate(entity)
    
    @staticmethod
    async def delete(
        endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an LLM endpoint by ID.
        
        Note: Cascade delete will also remove all associated level endpoint assignments.
        
        Args:
            endpoint_id: UUID of the endpoint to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(LLMEndpointEntity).where(LLMEndpointEntity.id == endpoint_id)
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
        endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an LLM endpoint exists.
        
        Args:
            endpoint_id: UUID of the endpoint to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if endpoint exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(LLMEndpointEntity.id).where(LLMEndpointEntity.id == endpoint_id)
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
        """Count total number of LLM endpoints.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of LLM endpoints in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(LLMEndpointEntity)
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