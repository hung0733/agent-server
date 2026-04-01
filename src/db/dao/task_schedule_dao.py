# pyright: reportMissingImports=false
"""
Data Access Object for TaskSchedule entity.

This module provides static methods for CRUD operations on TaskSchedule
entities. TaskSchedule manages recurring task execution patterns with 
support for cron, interval, and one-time schedules.

All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.task_schedule_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.task_schedule_dto import (
    TaskSchedule,
    TaskScheduleCreate,
    TaskScheduleUpdate,
)
from db.entity.task_schedule_entity import TaskSchedule as TaskScheduleEntity


class TaskScheduleDAO:
    """Data Access Object for TaskSchedule database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a schedule
        schedule_dto = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task_id,
                schedule_expression="0 12 * * *"
            )
        )
        
        # Get schedule by ID
        schedule = await TaskScheduleDAO.get_by_id(schedule_id)
        
        # Get schedule by task template
        schedule = await TaskScheduleDAO.get_by_task_template_id(task_id)
        
        # Update schedule
        updated = await TaskScheduleDAO.update(
            TaskScheduleUpdate(id=schedule_id, is_active=False)
        )
        
        # Delete schedule
        success = await TaskScheduleDAO.delete(schedule_id)
        
        # Get active schedules ready for execution
        active = await TaskScheduleDAO.get_active_schedules(session)
    """
    
    @staticmethod
    async def create(
        dto: TaskScheduleCreate,
        session: Optional[AsyncSession] = None,
    ) -> TaskSchedule:
        """Create a new task schedule.
        
        Args:
            dto: TaskScheduleCreate DTO with schedule data.
            session: Optional async session for transaction control.
            
        Returns:
            TaskSchedule DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key or unique constraint violated.
        """
        entity = TaskScheduleEntity(
            task_template_id=dto.task_template_id,
            schedule_type=dto.schedule_type,
            schedule_expression=dto.schedule_expression,
            is_active=dto.is_active,
            next_run_at=dto.next_run_at,
            last_run_at=dto.last_run_at,
        )
        
        if session is not None:
            session.add(entity)
            await session.flush()
            await session.refresh(entity)
        else:
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()

        return TaskSchedule.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        schedule_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskSchedule]:
        """Retrieve a task schedule by ID.
        
        Args:
            schedule_id: UUID of the schedule to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            TaskSchedule DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[TaskScheduleEntity]:
            result = await s.execute(
                select(TaskScheduleEntity).where(TaskScheduleEntity.id == schedule_id)
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
        return TaskSchedule.model_validate(entity)
    
    @staticmethod
    async def get_by_task_template_id(
        task_template_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskSchedule]:
        """Retrieve a schedule by task_template_id.
        
        Since each task can have at most one schedule, this returns
        a single schedule or None.
        
        Args:
            task_template_id: UUID of the task template.
            session: Optional async session for transaction control.
            
        Returns:
            TaskSchedule DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[TaskScheduleEntity]:
            result = await s.execute(
                select(TaskScheduleEntity).where(
                    TaskScheduleEntity.task_template_id == task_template_id
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
        return TaskSchedule.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        is_active: Optional[bool] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskSchedule]:
        """Retrieve all task schedules with optional filtering.
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            is_active: Optional filter for active/inactive schedules.
            session: Optional async session for transaction control.
            
        Returns:
            List of TaskSchedule DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskScheduleEntity]:
            query = select(TaskScheduleEntity)
            if is_active is not None:
                query = query.where(TaskScheduleEntity.is_active == is_active)
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
        
        return [TaskSchedule.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_active_schedules(
        session: Optional[AsyncSession] = None,
    ) -> List[TaskSchedule]:
        """Retrieve all active schedules with next_run_at set.
        
        This is used by the scheduler service to find schedules
        that are ready for execution.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            List of active TaskSchedule DTOs with next_run_at set.
        """
        async def _query(s: AsyncSession) -> List[TaskScheduleEntity]:
            result = await s.execute(
                select(TaskScheduleEntity).where(
                    TaskScheduleEntity.is_active == True,
                    TaskScheduleEntity.next_run_at.isnot(None),
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
        
        return [TaskSchedule.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: TaskScheduleUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskSchedule]:
        """Update an existing task schedule.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: TaskScheduleUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated TaskSchedule DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[TaskScheduleEntity]:
            entity = await s.get(TaskScheduleEntity, dto.id)
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
        return TaskSchedule.model_validate(entity)
    
    @staticmethod
    async def delete(
        schedule_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a task schedule by ID.
        
        Args:
            schedule_id: UUID of the schedule to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(TaskScheduleEntity).where(TaskScheduleEntity.id == schedule_id)
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
        schedule_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a task schedule exists.
        
        Args:
            schedule_id: UUID of the schedule to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if schedule exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(TaskScheduleEntity.id).where(TaskScheduleEntity.id == schedule_id)
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
        """Count total number of task schedules.

        Args:
            session: Optional async session for transaction control.

        Returns:
            Total count of task schedules in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(TaskScheduleEntity)
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
    async def get_due_schedules(
        current_time,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskSchedule]:
        """Retrieve all due schedules ready for execution.

        Returns active schedules where next_run_at <= current_time.
        Used by the scheduler service to find tasks to execute.

        Args:
            current_time: Current datetime to compare against next_run_at.
            session: Optional async session for transaction control.

        Returns:
            List of due TaskSchedule DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskScheduleEntity]:
            result = await s.execute(
                select(TaskScheduleEntity).where(
                    TaskScheduleEntity.is_active == True,
                    TaskScheduleEntity.next_run_at.isnot(None),
                    TaskScheduleEntity.next_run_at <= current_time,
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

        return [TaskSchedule.model_validate(e) for e in entities]