# pyright: reportMissingImports=false
"""
Data Access Object for AgentMessage entity.

This module provides static methods for CRUD operations on AgentMessage
entities.

All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.agent_message_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.collaboration_dto import (
    AgentMessage,
    AgentMessageCreate,
    AgentMessageUpdate,
)
from db.entity.collaboration_entity import AgentMessage as AgentMessageEntity
from db.types import MessageType


class AgentMessageDAO:
    """Data Access Object for AgentMessage database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create an agent message
        dto = await AgentMessageDAO.create(
            AgentMessageCreate(
                collaboration_id=collab_id,
                content_json={"action": "search"},
            )
        )
        
        # Get by ID
        message = await AgentMessageDAO.get_by_id(message_id)
        
        # Get by collaboration ID
        messages = await AgentMessageDAO.get_by_collaboration_id(collab_id)
        
        # Get by step_id
        messages = await AgentMessageDAO.get_by_step_id("step-001")
        
        # Update
        updated = await AgentMessageDAO.update(
            AgentMessageUpdate(id=message_id, content_json={"new": "content"})
        )
        
        # Delete
        success = await AgentMessageDAO.delete(message_id)
    """
    
    @staticmethod
    async def create(
        dto: AgentMessageCreate,
        session: Optional[AsyncSession] = None,
    ) -> AgentMessage:
        """Create a new agent message.
        
        Args:
            dto: AgentMessageCreate DTO with message data.
            session: Optional async session for transaction control.
            
        Returns:
            AgentMessage DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated.
        """
        entity = AgentMessageEntity(
            collaboration_id=dto.collaboration_id,
            step_id=dto.step_id,
            sender_agent_id=dto.sender_agent_id,
            receiver_agent_id=dto.receiver_agent_id,
            message_type=dto.message_type,
            content_json=dto.content_json,
            redaction_level=dto.redaction_level,
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
        
        return AgentMessage.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        message_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentMessage]:
        """Retrieve an agent message by ID.
        
        Args:
            message_id: UUID of the message to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            AgentMessage DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AgentMessageEntity]:
            result = await s.execute(
                select(AgentMessageEntity).where(AgentMessageEntity.id == message_id)
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
        return AgentMessage.model_validate(entity)
    
    @staticmethod
    async def get_by_collaboration_id(
        collaboration_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentMessage]:
        """Retrieve messages by collaboration ID.
        
        Messages are returned ordered by created_at ascending.
        
        Args:
            collaboration_id: UUID of the collaboration session.
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentMessage DTOs ordered by created_at ascending.
        """
        async def _query(s: AsyncSession) -> List[AgentMessageEntity]:
            result = await s.execute(
                select(AgentMessageEntity)
                .where(AgentMessageEntity.collaboration_id == collaboration_id)
                .order_by(AgentMessageEntity.created_at.asc())
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
        
        return [AgentMessage.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_step_id(
        step_id: str,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentMessage]:
        """Retrieve messages by step_id.
        
        Messages are returned ordered by created_at ascending.
        
        Args:
            step_id: The step identifier to filter by.
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentMessage DTOs with matching step_id.
        """
        async def _query(s: AsyncSession) -> List[AgentMessageEntity]:
            result = await s.execute(
                select(AgentMessageEntity)
                .where(AgentMessageEntity.step_id == step_id)
                .order_by(AgentMessageEntity.created_at.asc())
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
        
        return [AgentMessage.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        message_type: Optional[MessageType] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentMessage]:
        """Retrieve all agent messages with optional filtering.
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            message_type: Optional message type filter.
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentMessage DTOs.
        """
        async def _query(s: AsyncSession) -> List[AgentMessageEntity]:
            query = select(AgentMessageEntity)
            if message_type is not None:
                query = query.where(AgentMessageEntity.message_type == message_type)
            query = query.order_by(AgentMessageEntity.created_at.desc())
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
        
        return [AgentMessage.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: AgentMessageUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentMessage]:
        """Update an existing agent message.
        
        Only updates fields that are provided in the DTO.
        
        Args:
            dto: AgentMessageUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated AgentMessage DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[AgentMessageEntity]:
            entity = await s.get(AgentMessageEntity, dto.id)
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
        return AgentMessage.model_validate(entity)
    
    @staticmethod
    async def delete(
        message_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an agent message by ID.
        
        Args:
            message_id: UUID of the message to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(AgentMessageEntity).where(AgentMessageEntity.id == message_id)
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
        message_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an agent message exists.
        
        Args:
            message_id: UUID of the message to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if message exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(AgentMessageEntity.id).where(AgentMessageEntity.id == message_id)
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
        """Count total number of agent messages.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of agent messages in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(AgentMessageEntity)
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