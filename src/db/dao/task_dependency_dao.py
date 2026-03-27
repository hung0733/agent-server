# pyright: reportMissingImports=false
"""
Data Access Object for Task Dependency entity operations.

This module provides static methods for CRUD operations on Task Dependency entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.task_dependency_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.task_dependency_dto import TaskDependencyCreate, TaskDependency, TaskDependencyUpdate
from db.entity.task_dependency_entity import TaskDependency as TaskDependencyEntity


class TaskDependencyDAO:
    """Data Access Object for Task Dependency database operations.

    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.

    Example:
        # Create a dependency
        dep_dto = await TaskDependencyDAO.create(
            TaskDependencyCreate(
                parent_task_id=parent_id,
                child_task_id=child_id,
                dependency_type="sequential",
            )
        )

        # Get dependencies by parent task
        deps = await TaskDependencyDAO.get_by_parent_task(parent_id)

        # Get dependencies by child task
        deps = await TaskDependencyDAO.get_by_child_task(child_id)

        # Check if task can be executed (all dependencies met)
        can_run = await TaskDependencyDAO.are_dependencies_met(task_id)

        # Delete dependency
        success = await TaskDependencyDAO.delete(dep_id)
    """

    @staticmethod
    async def create(
        dto: TaskDependencyCreate,
        session: Optional[AsyncSession] = None,
    ) -> TaskDependency:
        """Create a new task dependency.

        Args:
            dto: TaskDependencyCreate DTO with dependency data.
            session: Optional async session for transaction control.

        Returns:
            TaskDependency DTO with populated ID and generated fields.

        Raises:
            IntegrityError: If unique constraint violated or foreign key invalid.
            ValueError: If parent_task_id == child_task_id (self-reference).
        """
        if dto.parent_task_id == dto.child_task_id:
            raise ValueError("Cannot create self-referencing dependency")

        entity = TaskDependencyEntity(
            parent_task_id=dto.parent_task_id,
            child_task_id=dto.child_task_id,
            dependency_type=dto.dependency_type,
            condition_json=dto.condition_json,
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

        return TaskDependency.model_validate(entity)

    @staticmethod
    async def get_by_id(
        dependency_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskDependency]:
        """Retrieve a task dependency by ID.

        Args:
            dependency_id: UUID of the dependency to retrieve.
            session: Optional async session for transaction control.

        Returns:
            TaskDependency DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[TaskDependencyEntity]:
            result = await s.execute(
                select(TaskDependencyEntity).where(TaskDependencyEntity.id == dependency_id)
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
        return TaskDependency.model_validate(entity)

    @staticmethod
    async def get_by_parent_task(
        parent_task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskDependency]:
        """Retrieve all dependencies where given task is the parent.

        Args:
            parent_task_id: UUID of the parent task.
            session: Optional async session for transaction control.

        Returns:
            List of TaskDependency DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskDependencyEntity]:
            result = await s.execute(
                select(TaskDependencyEntity).where(
                    TaskDependencyEntity.parent_task_id == parent_task_id
                )
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

        return [TaskDependency.model_validate(e) for e in entities]

    @staticmethod
    async def get_by_child_task(
        child_task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskDependency]:
        """Retrieve all dependencies where given task is the child.

        Args:
            child_task_id: UUID of the child task.
            session: Optional async session for transaction control.

        Returns:
            List of TaskDependency DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskDependencyEntity]:
            result = await s.execute(
                select(TaskDependencyEntity).where(
                    TaskDependencyEntity.child_task_id == child_task_id
                )
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

        return [TaskDependency.model_validate(e) for e in entities]

    @staticmethod
    async def are_dependencies_met(
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if all parent dependencies for a task are completed.

        A task can only run if all its parent tasks have completed successfully.

        Args:
            task_id: UUID of the task to check.
            session: Optional async session for transaction control.

        Returns:
            True if all dependencies are met (or no dependencies exist),
            False if any parent task is not yet completed.
        """
        async def _query(s: AsyncSession) -> bool:
            from db.entity.task_entity import Task as TaskEntity
            from db.types import TaskStatus

            # Get all parent dependencies
            result = await s.execute(
                select(TaskDependencyEntity).where(
                    TaskDependencyEntity.child_task_id == task_id
                )
            )
            dependencies = list(result.scalars().all())

            # No dependencies = can run
            if not dependencies:
                return True

            # Check if all parent tasks are completed
            for dep in dependencies:
                parent_result = await s.execute(
                    select(TaskEntity).where(TaskEntity.id == dep.parent_task_id)
                )
                parent_task = parent_result.scalar_one_or_none()

                if not parent_task:
                    # Parent task doesn't exist - cannot run
                    return False

                if parent_task.status != TaskStatus.completed:
                    # Parent task not completed - cannot run
                    return False

            # All parent tasks completed
            return True

        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                can_run = await _query(s)
            await engine.dispose()
            return can_run

    @staticmethod
    async def update(
        dto: TaskDependencyUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskDependency]:
        """Update an existing task dependency.

        Only updates fields that are provided in the DTO.

        Args:
            dto: TaskDependencyUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.

        Returns:
            Updated TaskDependency DTO if entity exists, None otherwise.

        Raises:
            IntegrityError: If constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[TaskDependencyEntity]:
            entity = await s.get(TaskDependencyEntity, dto.id)
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
        return TaskDependency.model_validate(entity)

    @staticmethod
    async def delete(
        dependency_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a task dependency by ID.

        Args:
            dependency_id: UUID of the dependency to delete.
            session: Optional async session for transaction control.

        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(TaskDependencyEntity).where(TaskDependencyEntity.id == dependency_id)
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
    async def count(
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count total number of task dependencies.

        Args:
            session: Optional async session for transaction control.

        Returns:
            Total count of task dependencies in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(TaskDependencyEntity)
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
