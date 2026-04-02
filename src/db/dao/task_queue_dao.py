# pyright: reportMissingImports=false
"""
Data Access Object for TaskQueue entity.

This module provides static methods for CRUD operations on TaskQueue
entities. All methods return DTOs and accept optional session parameters
for transaction control.

Import path: db.dao.task_queue_dao
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.task_queue_dto import TaskQueue, TaskQueueCreate, TaskQueueUpdate
from db.entity.task_queue_entity import TaskQueue as TaskQueueEntity
from db.types import TaskStatus


class TaskQueueDAO:
    """Data Access Object for TaskQueue database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a queue entry
        queue_dto = await TaskQueueDAO.create(
            TaskQueueCreate(task_id=task_id, priority=10)
        )
        
        # Get queue entry by ID
        entry = await TaskQueueDAO.get_by_id(queue_id)
        
        # Get entries by task ID
        entries = await TaskQueueDAO.get_by_task_id(task_id)
        
        # Get entries claimed by an agent
        claimed = await TaskQueueDAO.get_by_claimed_by(agent_id)
        
        # Update queue entry
        updated = await TaskQueueDAO.update(
            TaskQueueUpdate(id=queue_id, status=TaskStatus.running)
        )
        
        # Delete queue entry
        success = await TaskQueueDAO.delete(queue_id)
    """
    
    # =========================================================================
    # CRUD Operations
    # =========================================================================
    
    @staticmethod
    async def create(
        dto: TaskQueueCreate,
        session: Optional[AsyncSession] = None,
    ) -> TaskQueue:
        """Create a new queue entry.
        
        Args:
            dto: TaskQueueCreate DTO with queue entry data.
            session: Optional async session for transaction control.
            
        Returns:
            TaskQueue DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated.
        """
        entity = TaskQueueEntity(
            task_id=dto.task_id,
            status=dto.status,
            priority=dto.priority,
            queued_at=dto.queued_at,
            scheduled_at=dto.scheduled_at,
            started_at=dto.started_at,
            completed_at=dto.completed_at,
            claimed_by=dto.claimed_by,
            claimed_at=dto.claimed_at,
            retry_count=dto.retry_count,
            max_retries=dto.max_retries,
            error_message=dto.error_message,
            result_json=dto.result_json,
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
        
        return TaskQueue.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        queue_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskQueue]:
        """Retrieve a queue entry by ID.
        
        Args:
            queue_id: UUID of the queue entry to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            TaskQueue DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[TaskQueueEntity]:
            result = await s.execute(
                select(TaskQueueEntity).where(TaskQueueEntity.id == queue_id)
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
        return TaskQueue.model_validate(entity)
    
    @staticmethod
    async def get_by_task_id(
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskQueue]:
        """Retrieve queue entries by task ID.
        
        Args:
            task_id: UUID of the task.
            session: Optional async session for transaction control.
            
        Returns:
            List of TaskQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskQueueEntity]:
            result = await s.execute(
                select(TaskQueueEntity).where(TaskQueueEntity.task_id == task_id)
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
        
        return [TaskQueue.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_claimed_by(
        agent_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskQueue]:
        """Retrieve queue entries claimed by an agent.
        
        Args:
            agent_id: UUID of the claiming agent instance.
            session: Optional async session for transaction control.
            
        Returns:
            List of TaskQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskQueueEntity]:
            result = await s.execute(
                select(TaskQueueEntity).where(TaskQueueEntity.claimed_by == agent_id)
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
        
        return [TaskQueue.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        status: Optional[TaskStatus] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskQueue]:
        """Retrieve all queue entries with optional filtering.
        
        Returns entries ordered by priority DESC (highest priority first)
        for pending status, or by created_at DESC for other statuses.
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            status: Optional status filter.
            session: Optional async session for transaction control.
            
        Returns:
            List of TaskQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskQueueEntity]:
            query = select(TaskQueueEntity)
            
            if status is not None:
                query = query.where(TaskQueueEntity.status == status)
                # For pending status, order by priority DESC (highest first)
                if status == TaskStatus.pending:
                    query = query.order_by(
                        desc(TaskQueueEntity.priority),
                        TaskQueueEntity.scheduled_at.asc()
                    )
                else:
                    query = query.order_by(desc(TaskQueueEntity.created_at))
            else:
                # Default: pending tasks first (by priority), then others
                query = query.order_by(desc(TaskQueueEntity.priority))
            
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
        
        return [TaskQueue.model_validate(e) for e in entities]

    @staticmethod
    async def get_all_with_time_range(
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Optional[TaskStatus] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskQueue]:
        """Retrieve queue entries within a time range.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            start_time: Optional start time for queued_at (inclusive).
            end_time: Optional end time for queued_at (exclusive).
            status: Optional status filter.
            session: Optional async session for transaction control.

        Returns:
            List of TaskQueue DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskQueueEntity]:
            query = select(TaskQueueEntity)

            if start_time is not None:
                query = query.where(TaskQueueEntity.queued_at >= start_time)
            if end_time is not None:
                query = query.where(TaskQueueEntity.queued_at < end_time)
            if status is not None:
                query = query.where(TaskQueueEntity.status == status)
                if status == TaskStatus.pending:
                    query = query.order_by(
                        desc(TaskQueueEntity.priority),
                        TaskQueueEntity.scheduled_at.asc()
                    )
                else:
                    query = query.order_by(desc(TaskQueueEntity.created_at))
            else:
                query = query.order_by(desc(TaskQueueEntity.queued_at))

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

        return [TaskQueue.model_validate(e) for e in entities]

    @staticmethod
    async def update(
        dto: TaskQueueUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskQueue]:
        """Update an existing queue entry.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: TaskQueueUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated TaskQueue DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[TaskQueueEntity]:
            entity = await s.get(TaskQueueEntity, dto.id)
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
        return TaskQueue.model_validate(entity)
    
    @staticmethod
    async def delete(
        queue_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a queue entry by ID.
        
        Args:
            queue_id: UUID of the queue entry to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(TaskQueueEntity).where(TaskQueueEntity.id == queue_id)
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
        queue_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a queue entry exists.
        
        Args:
            queue_id: UUID of the queue entry to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if queue entry exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(TaskQueueEntity.id).where(TaskQueueEntity.id == queue_id)
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
        """Count total number of queue entries.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of queue entries in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(TaskQueueEntity)
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