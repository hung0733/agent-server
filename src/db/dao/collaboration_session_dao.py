# pyright: reportMissingImports=false
"""
Data Access Object for CollaborationSession entity.

This module provides static methods for CRUD operations on CollaborationSession
entities.

All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.collaboration_session_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.collaboration_dto import (
    CollaborationSession,
    CollaborationSessionCreate,
    CollaborationSessionUpdate,
)
from db.entity.collaboration_entity import CollaborationSession as CollaborationSessionEntity
from db.types import CollaborationStatus


class CollaborationSessionDAO:
    """Data Access Object for CollaborationSession database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a collaboration session
        dto = await CollaborationSessionDAO.create(
            CollaborationSessionCreate(
                user_id=user_id,
                main_agent_id=agent_id,
                session_id="session-xxx",
            )
        )
        
        # Get by ID
        session = await CollaborationSessionDAO.get_by_id(session_id)
        
        # Get by session_id
        session = await CollaborationSessionDAO.get_by_session_id("session-xxx")
        
        # Get by user ID
        sessions = await CollaborationSessionDAO.get_by_user_id(user_id)
        
        # Update
        updated = await CollaborationSessionDAO.update(
            CollaborationSessionUpdate(id=session_id, status="completed")
        )
        
        # Delete
        success = await CollaborationSessionDAO.delete(session_id)
    """
    
    @staticmethod
    async def create(
        dto: CollaborationSessionCreate,
        session: Optional[AsyncSession] = None,
    ) -> CollaborationSession:
        """Create a new collaboration session.
        
        Args:
            dto: CollaborationSessionCreate DTO with session data.
            session: Optional async session for transaction control.
            
        Returns:
            CollaborationSession DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key or unique constraint violated.
        """
        entity = CollaborationSessionEntity(
            user_id=dto.user_id,
            main_agent_id=dto.main_agent_id,
            name=dto.name,
            session_id=dto.session_id,
            status=dto.status,
            involves_secrets=dto.involves_secrets,
            context_json=dto.context_json,
        )
        
        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()
        
        return CollaborationSession.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        session_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[CollaborationSession]:
        """Retrieve a collaboration session by ID.
        
        Args:
            session_id: UUID of the session to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            CollaborationSession DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[CollaborationSessionEntity]:
            result = await s.execute(
                select(CollaborationSessionEntity).where(
                    CollaborationSessionEntity.id == session_id
                )
            )
            return result.scalar_one_or_none()
        
        if session is not None:
            entity = await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _query(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return CollaborationSession.model_validate(entity)
    
    @staticmethod
    async def get_by_session_id(
        unique_session_id: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[CollaborationSession]:
        """Retrieve a collaboration session by unique session_id.
        
        Args:
            unique_session_id: The unique session_id string.
            session: Optional async session for transaction control.
            
        Returns:
            CollaborationSession DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[CollaborationSessionEntity]:
            result = await s.execute(
                select(CollaborationSessionEntity).where(
                    CollaborationSessionEntity.session_id == unique_session_id
                )
            )
            return result.scalar_one_or_none()
        
        if session is not None:
            entity = await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _query(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return CollaborationSession.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[CollaborationSession]:
        """Retrieve collaboration sessions by user ID.
        
        Args:
            user_id: UUID of the owning user.
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            session: Optional async session for transaction control.
            
        Returns:
            List of CollaborationSession DTOs.
        """
        async def _query(s: AsyncSession) -> List[CollaborationSessionEntity]:
            result = await s.execute(
                select(CollaborationSessionEntity)
                .where(CollaborationSessionEntity.user_id == user_id)
                .order_by(CollaborationSessionEntity.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [CollaborationSession.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        status: Optional[CollaborationStatus] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[CollaborationSession]:
        """Retrieve all collaboration sessions with optional filtering.
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            status: Optional status filter.
            session: Optional async session for transaction control.
            
        Returns:
            List of CollaborationSession DTOs.
        """
        async def _query(s: AsyncSession) -> List[CollaborationSessionEntity]:
            query = select(CollaborationSessionEntity)
            if status is not None:
                query = query.where(CollaborationSessionEntity.status == status)
            query = query.order_by(CollaborationSessionEntity.created_at.desc())
            query = query.limit(limit).offset(offset)
            result = await s.execute(query)
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [CollaborationSession.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: CollaborationSessionUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[CollaborationSession]:
        """Update an existing collaboration session.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: CollaborationSessionUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated CollaborationSession DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[CollaborationSessionEntity]:
            entity = await s.get(CollaborationSessionEntity, dto.id)
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
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _update(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return CollaborationSession.model_validate(entity)
    
    @staticmethod
    async def delete(
        session_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a collaboration session by ID.
        
        Note: Cascade delete will also remove all associated agent messages.
        
        Args:
            session_id: UUID of the session to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(CollaborationSessionEntity).where(
                CollaborationSessionEntity.id == session_id
            )
            result = await s.execute(stmt)
            await s.commit()
            return result.rowcount > 0
        
        if session is not None:
            return await _delete(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                success = await _delete(s)
            await engine.dispose()
            return success
    
    @staticmethod
    async def exists(
        session_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a collaboration session exists.
        
        Args:
            session_id: UUID of the session to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if session exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(CollaborationSessionEntity.id).where(
                    CollaborationSessionEntity.id == session_id
                )
            )
            return result.scalar() is not None
        
        if session is not None:
            return await _query(session)
        else:
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
        """Count total number of collaboration sessions.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of collaboration sessions in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(CollaborationSessionEntity)
            )
            return result.scalar() or 0
        
        if session is not None:
            return await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count