# pyright: reportMissingImports=false
"""
Data Access Object for DeadLetterQueue entity.

This module provides static methods for CRUD operations on DeadLetterQueue
entities. All methods return DTOs and accept optional session parameters
for transaction control.

Import path: db.dao.dead_letter_queue_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.dead_letter_queue_dto import (
    DeadLetterQueue,
    DeadLetterQueueCreate,
    DeadLetterQueueUpdate,
)
from db.entity.dead_letter_queue_entity import DeadLetterQueue as DeadLetterQueueEntity


class DeadLetterQueueDAO:
    """Data Access Object for DeadLetterQueue database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a DLQ entry
        dlq_dto = await DeadLetterQueueDAO.create(
            DeadLetterQueueCreate(
                original_task_id=task_id,
                original_payload_json={"task": "data"},
                failure_reason="MaxRetriesExceeded",
                failure_details_json={"error": "test"},
            )
        )
        
        # Get DLQ entry by ID
        entry = await DeadLetterQueueDAO.get_by_id(dlq_id)
        
        # Get entries by original task ID
        entries = await DeadLetterQueueDAO.get_by_original_task_id(task_id)
        
        # Get active unresolved entries
        active = await DeadLetterQueueDAO.get_all(is_active=True)
        
        # Resolve a DLQ entry
        updated = await DeadLetterQueueDAO.update(
            DeadLetterQueueUpdate(
                id=dlq_id,
                is_active=False,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=user_id,
            )
        )
        
        # Delete DLQ entry
        success = await DeadLetterQueueDAO.delete(dlq_id)
    """
    
    # =========================================================================
    # CRUD Operations
    # =========================================================================
    
    @staticmethod
    async def create(
        dto: DeadLetterQueueCreate,
        session: Optional[AsyncSession] = None,
    ) -> DeadLetterQueue:
        """Create a new DLQ entry.
        
        Args:
            dto: DeadLetterQueueCreate DTO with DLQ entry data.
            session: Optional async session for transaction control.
            
        Returns:
            DeadLetterQueue DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated.
        """
        entity = DeadLetterQueueEntity(
            original_task_id=dto.original_task_id,
            original_queue_entry_id=dto.original_queue_entry_id,
            original_payload_json=dto.original_payload_json,
            failure_reason=dto.failure_reason,
            failure_details_json=dto.failure_details_json,
            retry_count=dto.retry_count,
            last_attempt_at=dto.last_attempt_at,
            is_active=dto.is_active,
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
        
        return DeadLetterQueue.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        dlq_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[DeadLetterQueue]:
        """Retrieve a DLQ entry by ID.
        
        Args:
            dlq_id: UUID of the DLQ entry to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            DeadLetterQueue DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[DeadLetterQueueEntity]:
            result = await s.execute(
                select(DeadLetterQueueEntity).where(DeadLetterQueueEntity.id == dlq_id)
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
        return DeadLetterQueue.model_validate(entity)
    
    @staticmethod
    async def get_by_original_task_id(
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[DeadLetterQueue]:
        """Retrieve DLQ entries by original_task_id.
        
        Args:
            task_id: UUID of the original task.
            session: Optional async session for transaction control.
            
        Returns:
            List of DeadLetterQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[DeadLetterQueueEntity]:
            result = await s.execute(
                select(DeadLetterQueueEntity).where(
                    DeadLetterQueueEntity.original_task_id == task_id
                )
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
        
        return [DeadLetterQueue.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_original_queue_entry_id(
        queue_entry_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[DeadLetterQueue]:
        """Retrieve DLQ entries by original_queue_entry_id.
        
        Args:
            queue_entry_id: UUID of the original queue entry.
            session: Optional async session for transaction control.
            
        Returns:
            List of DeadLetterQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[DeadLetterQueueEntity]:
            result = await s.execute(
                select(DeadLetterQueueEntity).where(
                    DeadLetterQueueEntity.original_queue_entry_id == queue_entry_id
                )
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
        
        return [DeadLetterQueue.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_resolved_by(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[DeadLetterQueue]:
        """Retrieve DLQ entries resolved by a specific user.
        
        Args:
            user_id: UUID of the user who resolved entries.
            session: Optional async session for transaction control.
            
        Returns:
            List of DeadLetterQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[DeadLetterQueueEntity]:
            result = await s.execute(
                select(DeadLetterQueueEntity).where(
                    DeadLetterQueueEntity.resolved_by == user_id
                ).order_by(desc(DeadLetterQueueEntity.resolved_at))
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
        
        return [DeadLetterQueue.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        is_active: Optional[bool] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[DeadLetterQueue]:
        """Retrieve all DLQ entries with optional filtering.
        
        Returns entries ordered by dead_lettered_at DESC (most recent first).
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            is_active: Optional filter for active status (True = unresolved).
            session: Optional async session for transaction control.
            
        Returns:
            List of DeadLetterQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[DeadLetterQueueEntity]:
            query = select(DeadLetterQueueEntity)
            
            if is_active is not None:
                query = query.where(DeadLetterQueueEntity.is_active == is_active)
            
            # Order by most recent first
            query = query.order_by(desc(DeadLetterQueueEntity.dead_lettered_at))
            
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
        
        return [DeadLetterQueue.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: DeadLetterQueueUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[DeadLetterQueue]:
        """Update an existing DLQ entry.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: DeadLetterQueueUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated DeadLetterQueue DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[DeadLetterQueueEntity]:
            entity = await s.get(DeadLetterQueueEntity, dto.id)
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
        return DeadLetterQueue.model_validate(entity)
    
    @staticmethod
    async def delete(
        dlq_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a DLQ entry by ID.
        
        Args:
            dlq_id: UUID of the DLQ entry to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(DeadLetterQueueEntity).where(DeadLetterQueueEntity.id == dlq_id)
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
        dlq_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a DLQ entry exists.
        
        Args:
            dlq_id: UUID of the DLQ entry to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if DLQ entry exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(DeadLetterQueueEntity.id).where(DeadLetterQueueEntity.id == dlq_id)
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
        is_active: Optional[bool] = None,
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count total number of DLQ entries.
        
        Args:
            is_active: Optional filter for active status.
            session: Optional async session for transaction control.
            
        Returns:
            Total count of DLQ entries matching filter.
        """
        async def _query(s: AsyncSession) -> int:
            query = select(func.count()).select_from(DeadLetterQueueEntity)
            
            if is_active is not None:
                query = query.where(DeadLetterQueueEntity.is_active == is_active)
            
            result = await s.execute(query)
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