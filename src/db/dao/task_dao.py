# pyright: reportMissingImports=false
"""
Data Access Object for Task and TaskDependency entities.

This module provides static methods for CRUD operations on Task and TaskDependency
entities, plus DAG (Directed Acyclic Graph) operations for task dependencies.

All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.task_dao
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSession, async_sessionmaker, create_engine
from db.dto.task_dto import (
    Task,
    TaskCreate,
    TaskUpdate,
    TaskDependency,
    TaskDependencyCreate,
    TaskDependencyUpdate,
)
from db.entity.task_entity import Task as TaskEntity, TaskDependency as TaskDependencyEntity
from db.types import TaskStatus


class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the task dependency graph.
    
    Attributes:
        message: Human-readable error message.
        cycle_path: List of task IDs forming the detected cycle.
    """
    
    def __init__(self, message: str, cycle_path: Optional[List[UUID]] = None):
        super().__init__(message)
        self.cycle_path = cycle_path or []


class TaskDAO:
    """Data Access Object for Task database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Includes both CRUD methods and DAG operations for task dependencies.
    
    Example:
        # Create a task
        task_dto = await TaskDAO.create(TaskCreate(user_id=user_id, task_type="research"))
        
        # Get task by ID
        task = await TaskDAO.get_by_id(task_id)
        
        # Get tasks by user
        tasks = await TaskDAO.get_by_user_id(user_id)
        
        # Update task
        updated = await TaskDAO.update(TaskUpdate(id=task_id, status=TaskStatus.running))
        
        # Delete task
        success = await TaskDAO.delete(task_id)
        
        # DAG operations
        ancestors = await TaskDAO.get_ancestors(task_id, session)
        descendants = await TaskDAO.get_descendants(task_id, session)
        order = await TaskDAO.get_dependency_order([task_id1, task_id2], session)
        await TaskDAO.validate_new_dependency(parent_id, child_id, session)
    """
    
    # =========================================================================
    # CRUD Operations
    # =========================================================================
    
    @staticmethod
    async def create(
        dto: TaskCreate,
        session: Optional[AsyncSession] = None,
    ) -> Task:
        """Create a new task.
        
        Args:
            dto: TaskCreate DTO with task data.
            session: Optional async session for transaction control.
            
        Returns:
            Task DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated.
        """
        entity = TaskEntity(
            user_id=dto.user_id,
            agent_id=dto.agent_id,
            parent_task_id=dto.parent_task_id,
            task_type=dto.task_type,
            status=dto.status,
            priority=dto.priority,
            payload=dto.payload,
            result=dto.result,
            error_message=dto.error_message,
            retry_count=dto.retry_count,
            max_retries=dto.max_retries,
            scheduled_at=dto.scheduled_at,
            started_at=dto.started_at,
            completed_at=dto.completed_at,
            session_id=dto.session_id,
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
        
        return Task.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Task]:
        """Retrieve a task by ID.
        
        Args:
            task_id: UUID of the task to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            Task DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[TaskEntity]:
            result = await s.execute(
                select(TaskEntity).where(TaskEntity.id == task_id)
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
        return Task.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[Task]:
        """Retrieve tasks by user ID.
        
        Args:
            user_id: UUID of the owning user.
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            session: Optional async session for transaction control.
            
        Returns:
            List of Task DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskEntity]:
            result = await s.execute(
                select(TaskEntity)
                .where(TaskEntity.user_id == user_id)
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
        
        return [Task.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        status: Optional[TaskStatus] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[Task]:
        """Retrieve all tasks with optional filtering.
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            status: Optional status filter.
            session: Optional async session for transaction control.
            
        Returns:
            List of Task DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskEntity]:
            query = select(TaskEntity)
            if status is not None:
                query = query.where(TaskEntity.status == status)
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
        
        return [Task.model_validate(e) for e in entities]

    @staticmethod
    async def get_by_agent_id(
        agent_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[Task]:
        """Retrieve tasks by agent instance ID.

        Args:
            agent_id: UUID of the agent instance.
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            session: Optional async session for transaction control.

        Returns:
            List of Task DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskEntity]:
            result = await s.execute(
                select(TaskEntity)
                .where(TaskEntity.agent_id == agent_id)
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

        return [Task.model_validate(e) for e in entities]

    @staticmethod
    async def update(
        dto: TaskUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Task]:
        """Update an existing task.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: TaskUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated Task DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[TaskEntity]:
            entity = await s.get(TaskEntity, dto.id)
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
        return Task.model_validate(entity)
    
    @staticmethod
    async def delete(
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a task by ID.
        
        Note: Cascade delete will also remove all associated task dependencies
        and child tasks.
        
        Args:
            task_id: UUID of the task to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(TaskEntity).where(TaskEntity.id == task_id)
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
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a task exists.
        
        Args:
            task_id: UUID of the task to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if task exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(TaskEntity.id).where(TaskEntity.id == task_id)
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
        """Count total number of tasks.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of tasks in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(TaskEntity)
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
    
    # =========================================================================
    # DAG Operations
    # =========================================================================
    
    @staticmethod
    async def detect_cycle(
        parent_task_id: UUID,
        child_task_id: UUID,
        session: AsyncSession,
    ) -> Optional[List[UUID]]:
        """Check if adding a dependency would create a cycle in the task DAG.
        
        Uses DFS (Depth-First Search) to detect if there's a path from
        child_task_id to parent_task_id. If such a path exists, adding
        the dependency parent_task_id -> child_task_id would create a cycle.
        
        Args:
            parent_task_id: The proposed parent task ID.
            child_task_id: The proposed child task ID.
            session: AsyncSession for database queries.
            
        Returns:
            List of task IDs forming the cycle if detected, None otherwise.
        """
        # Build adjacency list from database
        result = await session.execute(
            select(TaskDependencyEntity.parent_task_id, TaskDependencyEntity.child_task_id)
        )
        dependencies = result.fetchall()
        
        # Build adjacency list: task -> tasks that depend on it
        adjacency: Dict[UUID, List[UUID]] = defaultdict(list)
        
        for row in dependencies:
            adj_parent, adj_child = row
            adjacency[adj_parent].append(adj_child)
        
        # DFS to check if there's a path from child to parent
        visited: Set[UUID] = set()
        path: List[UUID] = []
        
        def dfs(current: UUID, target: UUID) -> Optional[List[UUID]]:
            if current in visited:
                return None
            
            visited.add(current)
            path.append(current)
            
            if current == target:
                return list(path)
            
            for neighbor in adjacency.get(current, []):
                result_path = dfs(neighbor, target)
                if result_path:
                    return result_path
            
            path.pop()
            return None
        
        # Check if there's a path from child to parent
        cycle_path = dfs(child_task_id, parent_task_id)
        
        if cycle_path:
            return [parent_task_id] + cycle_path
        
        return None
    
    @staticmethod
    async def get_ancestors(
        task_id: UUID,
        session: AsyncSession,
    ) -> Set[UUID]:
        """Get all ancestor tasks (tasks this task depends on, directly or indirectly).
        
        Uses BFS to traverse the dependency graph upward.
        
        Args:
            task_id: The task ID to find ancestors for.
            session: AsyncSession for database queries.
            
        Returns:
            Set of ancestor task IDs.
        """
        ancestors: Set[UUID] = set()
        queue: List[UUID] = [task_id]
        
        while queue:
            current = queue.pop(0)
            
            result = await session.execute(
                select(TaskDependencyEntity.parent_task_id).where(
                    TaskDependencyEntity.child_task_id == current
                )
            )
            parents = [row[0] for row in result.fetchall()]
            
            for parent_id in parents:
                if parent_id not in ancestors:
                    ancestors.add(parent_id)
                    queue.append(parent_id)
        
        return ancestors
    
    @staticmethod
    async def get_descendants(
        task_id: UUID,
        session: AsyncSession,
    ) -> Set[UUID]:
        """Get all descendant tasks (tasks that depend on this task, directly or indirectly).
        
        Uses BFS to traverse the dependency graph downward.
        
        Args:
            task_id: The task ID to find descendants for.
            session: AsyncSession for database queries.
            
        Returns:
            Set of descendant task IDs.
        """
        descendants: Set[UUID] = set()
        queue: List[UUID] = [task_id]
        
        while queue:
            current = queue.pop(0)
            
            result = await session.execute(
                select(TaskDependencyEntity.child_task_id).where(
                    TaskDependencyEntity.parent_task_id == current
                )
            )
            children = [row[0] for row in result.fetchall()]
            
            for child_id in children:
                if child_id not in descendants:
                    descendants.add(child_id)
                    queue.append(child_id)
        
        return descendants
    
    @staticmethod
    async def get_dependency_order(
        task_ids: List[UUID],
        session: AsyncSession,
    ) -> List[UUID]:
        """Get tasks in dependency order (topological sort).
        
        Returns tasks sorted such that all dependencies come before
        the tasks that depend on them.
        
        Args:
            task_ids: List of task IDs to sort.
            session: AsyncSession for database queries.
            
        Returns:
            List of task IDs in dependency order.
            
        Raises:
            CycleDetectedError: If a cycle is detected in the dependencies.
        """
        if not task_ids:
            return []
        
        task_set = set(task_ids)
        
        # Get all dependencies among the given tasks
        result = await session.execute(
            select(TaskDependencyEntity.parent_task_id, TaskDependencyEntity.child_task_id).where(
                TaskDependencyEntity.parent_task_id.in_(task_ids),
                TaskDependencyEntity.child_task_id.in_(task_ids),
            )
        )
        dependencies = result.fetchall()
        
        # Build in-degree map and adjacency list
        in_degree: Dict[UUID, int] = {tid: 0 for tid in task_ids}
        adjacency: Dict[UUID, List[UUID]] = defaultdict(list)
        
        for parent_id, child_id in dependencies:
            adjacency[parent_id].append(child_id)
            in_degree[child_id] += 1
        
        # Kahn's algorithm for topological sort
        result_order: List[UUID] = []
        queue: List[UUID] = [tid for tid in task_ids if in_degree[tid] == 0]
        
        while queue:
            current = queue.pop(0)
            result_order.append(current)
            
            for dependent in adjacency.get(current, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # If not all tasks are in result, there's a cycle
        if len(result_order) != len(task_ids):
            raise CycleDetectedError(
                "Cycle detected in task dependencies",
                [tid for tid in task_ids if tid not in result_order]
            )
        
        return result_order
    
    @staticmethod
    async def validate_new_dependency(
        parent_task_id: UUID,
        child_task_id: UUID,
        session: AsyncSession,
    ) -> None:
        """Validate that a new dependency can be safely added.
        
        Checks:
        1. No self-reference (parent != child)
        2. No cycle would be created
        
        Args:
            parent_task_id: The proposed parent task ID.
            child_task_id: The proposed child task ID.
            session: AsyncSession for database queries.
            
        Raises:
            ValueError: If parent_task_id == child_task_id.
            CycleDetectedError: If adding the dependency would create a cycle.
        """
        # Check self-reference
        if parent_task_id == child_task_id:
            raise ValueError(
                f"Task cannot depend on itself: {parent_task_id}"
            )
        
        # Check for cycles
        cycle_path = await TaskDAO.detect_cycle(parent_task_id, child_task_id, session)
        if cycle_path:
            cycle_str = " -> ".join(str(tid) for tid in cycle_path)
            raise CycleDetectedError(
                f"Adding dependency would create a cycle: {cycle_str}",
                cycle_path
            )


class TaskDependencyDAO:
    """Data Access Object for TaskDependency database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
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
            TaskDependency DTO with populated ID.
            
        Raises:
            IntegrityError: If foreign key or unique constraint violated.
        """
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
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _query(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return TaskDependency.model_validate(entity)
    
    @staticmethod
    async def get_by_parent_task_id(
        parent_task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskDependency]:
        """Retrieve dependencies by parent task ID.
        
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
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [TaskDependency.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_child_task_id(
        child_task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskDependency]:
        """Retrieve dependencies by child task ID.
        
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
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [TaskDependency.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[TaskDependency]:
        """Retrieve all task dependencies with pagination.
        
        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            session: Optional async session for transaction control.
            
        Returns:
            List of TaskDependency DTOs.
        """
        async def _query(s: AsyncSession) -> List[TaskDependencyEntity]:
            result = await s.execute(
                select(TaskDependencyEntity).limit(limit).offset(offset)
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
        
        return [TaskDependency.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: TaskDependencyUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TaskDependency]:
        """Update an existing task dependency.
        
        Args:
            dto: TaskDependencyUpdate DTO with fields to update.
            session: Optional async session for transaction control.
            
        Returns:
            Updated TaskDependency DTO if entity exists, None otherwise.
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
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                success = await _delete(s)
            await engine.dispose()
            return success
    
    @staticmethod
    async def exists(
        dependency_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a task dependency exists.
        
        Args:
            dependency_id: UUID of the dependency to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if dependency exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(TaskDependencyEntity.id).where(TaskDependencyEntity.id == dependency_id)
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
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count