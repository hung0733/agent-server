# pyright: reportMissingImports=false
"""
Data Access Object for AgentCapability entity operations.

This module provides static methods for CRUD operations on AgentCapability entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.agent_capability_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.agent_capability_dto import (
    AgentCapabilityCreate,
    AgentCapability,
    AgentCapabilityUpdate,
)
from db.entity.agent_capability_entity import AgentCapability as AgentCapabilityEntity


class AgentCapabilityDAO:
    """Data Access Object for AgentCapability database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a capability
        capability_dto = await AgentCapabilityDAO.create(
            AgentCapabilityCreate(
                agent_type_id=agent_type_id,
                capability_name="web_search",
                description="Search the web for information",
            )
        )
        
        # Get capability by ID
        capability = await AgentCapabilityDAO.get_by_id(capability_id)
        
        # Get capabilities by agent type
        capabilities = await AgentCapabilityDAO.get_by_agent_type_id(agent_type_id)
        
        # Update capability
        updated = await AgentCapabilityDAO.update(
            AgentCapabilityUpdate(id=capability_id, description="New description")
        )
        
        # Delete capability
        success = await AgentCapabilityDAO.delete(capability_id)
    """
    
    @staticmethod
    async def create(
        dto: AgentCapabilityCreate,
        session: Optional[AsyncSession] = None,
    ) -> AgentCapability:
        """Create a new agent capability.
        
        Args:
            dto: AgentCapabilityCreate DTO with capability data.
            session: Optional async session for transaction control.
            
        Returns:
            AgentCapability DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated (invalid agent_type_id).
        """
        entity = AgentCapabilityEntity(
            agent_type_id=dto.agent_type_id,
            capability_name=dto.capability_name,
            description=dto.description,
            input_schema=dto.input_schema,
            output_schema=dto.output_schema,
            is_active=dto.is_active,
        )
        
        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            # Create internal session if none provided
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()
        
        return AgentCapability.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        capability_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentCapability]:
        """Retrieve an agent capability by ID.
        
        Args:
            capability_id: UUID of the capability to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            AgentCapability DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AgentCapabilityEntity]:
            result = await s.execute(
                select(AgentCapabilityEntity).where(AgentCapabilityEntity.id == capability_id)
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
        return AgentCapability.model_validate(entity)
    
    @staticmethod
    async def get_by_agent_type_id(
        agent_type_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentCapability]:
        """Retrieve capabilities by agent_type_id.
        
        Args:
            agent_type_id: UUID of the agent type.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentCapability DTOs for the agent type.
        """
        async def _query(s: AsyncSession) -> List[AgentCapabilityEntity]:
            result = await s.execute(
                select(AgentCapabilityEntity)
                .where(AgentCapabilityEntity.agent_type_id == agent_type_id)
                .order_by(AgentCapabilityEntity.created_at.desc())
                .limit(limit)
                .offset(offset)
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
        
        return [AgentCapability.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        active_only: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentCapability]:
        """Retrieve all capabilities with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            active_only: If True, only return active capabilities.
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentCapability DTOs.
        """
        async def _query(s: AsyncSession) -> List[AgentCapabilityEntity]:
            query = select(AgentCapabilityEntity)
            if active_only:
                query = query.where(AgentCapabilityEntity.is_active.is_(True))
            query = query.limit(limit).offset(offset)
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
        
        return [AgentCapability.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: AgentCapabilityUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentCapability]:
        """Update an existing capability.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: AgentCapabilityUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated AgentCapability DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[AgentCapabilityEntity]:
            # Fetch existing entity
            entity = await s.get(AgentCapabilityEntity, dto.id)
            if entity is None:
                return None
            
            # Update only provided fields
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
        return AgentCapability.model_validate(entity)
    
    @staticmethod
    async def delete(
        capability_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a capability by ID.
        
        Args:
            capability_id: UUID of the capability to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(AgentCapabilityEntity).where(AgentCapabilityEntity.id == capability_id)
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
        capability_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a capability exists.
        
        Args:
            capability_id: UUID of the capability to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if capability exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(AgentCapabilityEntity.id).where(AgentCapabilityEntity.id == capability_id)
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
        """Count total number of capabilities.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of capabilities in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(AgentCapabilityEntity)
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