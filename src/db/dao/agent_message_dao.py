# pyright: reportMissingImports=false
"""
Data Access Object for AgentMessage entity.

This module provides static methods for CRUD operations on AgentMessage
entities.

All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.agent_message_dao
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select, and_, or_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.collaboration_dto import (
    AgentMessage,
    AgentMessageCreate,
    AgentMessageUpdate,
)
from db.entity.collaboration_entity import AgentMessage as AgentMessageEntity
from db.entity.collaboration_entity import CollaborationSession as CollaborationSessionEntity
from db.entity.agent_entity import AgentInstance as AgentInstanceEntity
from db.types import MessageType
from utils.timezone import to_server_tz


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
    async def batch_update_is_summarized(
        message_ids: List[UUID],
        is_summarized: bool = True,
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Batch update is_summarized flag for multiple messages.

        More efficient than updating messages one by one.
        Uses a single UPDATE query with WHERE id IN (...).

        Args:
            message_ids: List of message UUIDs to update.
            is_summarized: Value to set (default True).
            session: Optional async session for transaction control.

        Returns:
            Number of messages updated.
        """
        if not message_ids:
            return 0

        from sqlalchemy import update

        async def _batch_update(s: AsyncSession) -> int:
            stmt = (
                update(AgentMessageEntity)
                .where(AgentMessageEntity.id.in_(message_ids))
                .values(is_summarized=is_summarized)
            )
            result = await s.execute(stmt)
            await s.commit()
            return result.rowcount

        if session is not None:
            return await _batch_update(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _batch_update(s)
            await engine.dispose()
            return count

    @staticmethod
    async def batch_update_is_analyzed(
        message_ids: List[UUID],
        is_analyzed: bool = True,
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Batch update is_analyzed flag for multiple messages."""
        if not message_ids:
            return 0

        from sqlalchemy import update

        async def _batch_update(s: AsyncSession) -> int:
            stmt = (
                update(AgentMessageEntity)
                .where(AgentMessageEntity.id.in_(message_ids))
                .values(is_analyzed=is_analyzed)
            )
            result = await s.execute(stmt)
            await s.commit()
            return result.rowcount

        if session is not None:
            return await _batch_update(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _batch_update(s)
            await engine.dispose()
            return count

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

    @staticmethod
    async def get_all_with_session_id(
        limit: int = 100,
        offset: int = 0,
        message_type: Optional[MessageType] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[tuple[AgentMessage, str]]:
        """Retrieve all agent messages with their session_id.

        This method joins with CollaborationSession to include the session_id
        string in the results, which is needed for determining display names
        in the dashboard.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            message_type: Optional message type filter.
            session: Optional async session for transaction control.

        Returns:
            List of tuples: (AgentMessage DTO, session_id string).
        """
        async def _query(s: AsyncSession) -> List[tuple[AgentMessage, str]]:
            query = (
                select(AgentMessageEntity, CollaborationSessionEntity.session_id)
                .join(
                    CollaborationSessionEntity,
                    AgentMessageEntity.collaboration_id == CollaborationSessionEntity.id,
                )
            )
            if message_type is not None:
                query = query.where(AgentMessageEntity.message_type == message_type)
            query = query.order_by(AgentMessageEntity.created_at.desc())
            query = query.limit(limit).offset(offset)
            result = await s.execute(query)
            rows = result.all()
            return [
                (AgentMessage.model_validate(entity), session_id)
                for entity, session_id in rows
            ]

        if session is not None:
            return await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                results = await _query(s)
            await engine.dispose()
            return results

    @staticmethod
    async def get_all_with_session_id_and_time_range(
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        message_type: Optional[MessageType] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[tuple[AgentMessage, str]]:
        """Retrieve agent messages within a time range with session_id.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            start_time: Optional start time (inclusive).
            end_time: Optional end time (exclusive).
            message_type: Optional message type filter.
            session: Optional async session for transaction control.

        Returns:
            List of tuples: (AgentMessage DTO, session_id string).
        """
        async def _query(s: AsyncSession) -> List[tuple[AgentMessage, str]]:
            query = (
                select(AgentMessageEntity, CollaborationSessionEntity.session_id)
                .join(
                    CollaborationSessionEntity,
                    AgentMessageEntity.collaboration_id == CollaborationSessionEntity.id,
                )
            )
            if start_time is not None:
                query = query.where(AgentMessageEntity.created_at >= start_time)
            if end_time is not None:
                query = query.where(AgentMessageEntity.created_at < end_time)
            if message_type is not None:
                query = query.where(AgentMessageEntity.message_type == message_type)
            query = query.order_by(AgentMessageEntity.created_at.desc())
            query = query.limit(limit).offset(offset)
            result = await s.execute(query)
            rows = result.all()
            return [
                (AgentMessage.model_validate(entity), session_id)
                for entity, session_id in rows
            ]

        if session is not None:
            return await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                results = await _query(s)
            await engine.dispose()
            return results

    @staticmethod
    async def get_unsummarized_messages_grouped(
        agent_id: str,
        before_date: datetime,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Dict[str, List[AgentMessage]]]:
        """Retrieve unsummarized messages grouped by date and session_id.

        This method finds all agent messages that:
        - Belong to the specified agent (by agent_id string)
        - Have is_summarized = False
        - Were created before the specified date
        - Belong to sessions starting with 'agent-' or 'session-'

        Results are grouped by date (YYYY-MM-DD) and session_id, sorted by
        date ASC and session_id ASC.

        Args:
            agent_id: String identifier of the agent (e.g., 'agent-001').
            before_date: Only include messages created before this datetime.
            session: Optional async session for transaction control.

        Returns:
            Nested dict: {date_str: {session_id: [AgentMessage, ...]}}
            Example: {"2026-03-26": {"session-001": [msg1, msg2], "agent-002": [msg3]}}
        """
        async def _query(s: AsyncSession) -> Dict[str, Dict[str, List[AgentMessage]]]:
            # Build query with joins
            query = (
                select(AgentMessageEntity, CollaborationSessionEntity.session_id)
                .join(
                    CollaborationSessionEntity,
                    AgentMessageEntity.collaboration_id == CollaborationSessionEntity.id
                )
                .join(
                    AgentInstanceEntity,
                    CollaborationSessionEntity.main_agent_id == AgentInstanceEntity.id
                )
                .where(
                    and_(
                        AgentInstanceEntity.agent_id == agent_id,
                        AgentMessageEntity.is_summarized == False,  # noqa: E712
                        AgentMessageEntity.created_at < before_date,
                        or_(
                            CollaborationSessionEntity.session_id.like('session-%'),
                            CollaborationSessionEntity.session_id.like('default-%'),
                        )
                    )
                )
                .order_by(
                    AgentMessageEntity.created_at.asc(),
                    CollaborationSessionEntity.session_id.asc()
                )
            )

            result = await s.execute(query)
            rows = result.all()

            # Group by date and session_id
            grouped: Dict[str, Dict[str, List[AgentMessage]]] = {}
            for message_entity, session_id in rows:
                # Extract date from created_at in server timezone
                created_at_server = to_server_tz(message_entity.created_at)
                date_str = created_at_server.date().isoformat()

                # Initialize nested dicts if needed
                if date_str not in grouped:
                    grouped[date_str] = {}
                if session_id not in grouped[date_str]:
                    grouped[date_str][session_id] = []

                # Convert entity to DTO and append
                message_dto = AgentMessage.model_validate(message_entity)
                grouped[date_str][session_id].append(message_dto)

            # Sort the outer dict by date
            sorted_grouped = dict(sorted(grouped.items()))

            # Sort inner dicts by session_id
            for date_str in sorted_grouped:
                sorted_grouped[date_str] = dict(sorted(sorted_grouped[date_str].items()))

            return sorted_grouped

        if session is not None:
            return await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                result = await _query(s)
            await engine.dispose()
            return result

    @staticmethod
    async def get_unanalyzed_messages_grouped(
        agent_id: str,
        before_date: datetime,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Dict[str, List[AgentMessage]]]:
        """Retrieve unanalyzed messages grouped by date and session_id."""

        async def _query(s: AsyncSession) -> Dict[str, Dict[str, List[AgentMessage]]]:
            query = (
                select(AgentMessageEntity, CollaborationSessionEntity.session_id)
                .join(
                    CollaborationSessionEntity,
                    AgentMessageEntity.collaboration_id == CollaborationSessionEntity.id,
                )
                .join(
                    AgentInstanceEntity,
                    CollaborationSessionEntity.main_agent_id == AgentInstanceEntity.id,
                )
                .where(
                    and_(
                        AgentInstanceEntity.agent_id == agent_id,
                        AgentMessageEntity.is_analyzed == False,  # noqa: E712
                        AgentMessageEntity.created_at < before_date,
                        or_(
                            CollaborationSessionEntity.session_id.like("session-%"),
                            CollaborationSessionEntity.session_id.like("default-%"),
                            CollaborationSessionEntity.session_id.like("ghost-%"),
                        ),
                    )
                )
                .order_by(
                    AgentMessageEntity.created_at.asc(),
                    CollaborationSessionEntity.session_id.asc(),
                )
            )

            result = await s.execute(query)
            rows = result.all()

            grouped: Dict[str, Dict[str, List[AgentMessage]]] = {}
            for message_entity, session_id in rows:
                created_at_server = to_server_tz(message_entity.created_at)
                date_str = created_at_server.date().isoformat()

                if date_str not in grouped:
                    grouped[date_str] = {}
                if session_id not in grouped[date_str]:
                    grouped[date_str][session_id] = []

                message_dto = AgentMessage.model_validate(message_entity)
                grouped[date_str][session_id].append(message_dto)

            sorted_grouped = dict(sorted(grouped.items()))
            for grouped_date in sorted_grouped:
                sorted_grouped[grouped_date] = dict(sorted(sorted_grouped[grouped_date].items()))

            return sorted_grouped

        if session is not None:
            return await _query(session)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                result = await _query(s)
            await engine.dispose()
            return result
