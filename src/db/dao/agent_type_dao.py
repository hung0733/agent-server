# pyright: reportMissingImports=false
"""
Data Access Object for AgentType entity operations.

This module provides static methods for CRUD operations on AgentType entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.agent_type_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.agent_dto import AgentTypeCreate, AgentType, AgentTypeUpdate
from db.entity.agent_entity import AgentType as AgentTypeEntity


class AgentTypeDAO:
    """Data Access Object for AgentType database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create an agent type
        agent_type_dto = await AgentTypeDAO.create(
            AgentTypeCreate(name="ResearchAgent", description="Web research agent")
        )
        
        # Get agent type by ID
        agent_type = await AgentTypeDAO.get_by_id(agent_type_id)
        
        # Get agent type by name
        agent_type = await AgentTypeDAO.get_by_name("ResearchAgent")
        
        # Update agent type
        updated = await AgentTypeDAO.update(
            AgentTypeUpdate(id=agent_type_id, description="New description")
        )
        
        # Delete agent type
        success = await AgentTypeDAO.delete(agent_type_id)
    """
    
    @staticmethod
    async def create(
        dto: AgentTypeCreate,
        session: Optional[AsyncSession] = None,
    ) -> AgentType:
        """Create a new agent type.
        
        Args:
            dto: AgentTypeCreate DTO with agent type data.
            session: Optional async session for transaction control.
            
        Returns:
            AgentType DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If unique constraint violated (duplicate name).
        """
        entity = AgentTypeEntity(
            name=dto.name,
            description=dto.description,
            capabilities=dto.capabilities,
            default_config=dto.default_config,
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
        
        return AgentType.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        agent_type_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentType]:
        """Retrieve an agent type by ID.
        
        Args:
            agent_type_id: UUID of the agent type to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            AgentType DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AgentTypeEntity]:
            result = await s.execute(
                select(AgentTypeEntity).where(AgentTypeEntity.id == agent_type_id)
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
        return AgentType.model_validate(entity)
    
    @staticmethod
    async def get_by_name(
        name: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentType]:
        """Retrieve an agent type by name.
        
        Args:
            name: Name of the agent type to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            AgentType DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AgentTypeEntity]:
            result = await s.execute(
                select(AgentTypeEntity).where(AgentTypeEntity.name == name)
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
        return AgentType.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        active_only: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentType]:
        """Retrieve all agent types with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            active_only: If True, only return active agent types.
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentType DTOs.
        """
        async def _query(s: AsyncSession) -> List[AgentTypeEntity]:
            query = select(AgentTypeEntity)
            if active_only:
                query = query.where(AgentTypeEntity.is_active.is_(True))
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
        
        return [AgentType.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: AgentTypeUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentType]:
        """Update an existing agent type.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: AgentTypeUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated AgentType DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[AgentTypeEntity]:
            # Fetch existing entity
            entity = await s.get(AgentTypeEntity, dto.id)
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
        return AgentType.model_validate(entity)
    
    @staticmethod
    async def delete(
        agent_type_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an agent type by ID.
        
        Note: Cascade delete will also remove all associated agent instances.
        
        Args:
            agent_type_id: UUID of the agent type to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(AgentTypeEntity).where(AgentTypeEntity.id == agent_type_id)
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
        agent_type_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an agent type exists.
        
        Args:
            agent_type_id: UUID of the agent type to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if agent type exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(AgentTypeEntity.id).where(AgentTypeEntity.id == agent_type_id)
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
        """Count total number of agent types.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of agent types in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(AgentTypeEntity)
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