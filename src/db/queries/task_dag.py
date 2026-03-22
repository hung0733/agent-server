# pyright: reportMissingImports=false
"""
DAG (Directed Acyclic Graph) operations for task dependencies.

This module provides helper functions for managing and validating
task dependency graphs, including cycle detection to prevent
circular dependencies.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Set, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from db.schema.task_dependencies import TaskDependency


class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the task dependency graph."""
    
    def __init__(self, message: str, cycle_path: Optional[List[UUID]] = None):
        super().__init__(message)
        self.cycle_path = cycle_path or []


async def detect_cycle(
    session: AsyncSession,
    parent_task_id: UUID,
    child_task_id: UUID,
) -> Optional[List[UUID]]:
    """Check if adding a dependency would create a cycle in the task DAG.
    
    Uses DFS (Depth-First Search) to detect if there's a path from
    child_task_id to parent_task_id. If such a path exists, adding
    the dependency parent_task_id -> child_task_id would create a cycle.
    
    Args:
        session: AsyncSession for database queries.
        parent_task_id: The proposed parent task ID.
        child_task_id: The proposed child task ID.
        
    Returns:
        List of task IDs forming the cycle if detected, None otherwise.
        
    Example:
        # If we have: A -> B -> C
        # And we try to add: C -> A
        # This would create cycle: A -> B -> C -> A
        
        cycle = await detect_cycle(session, parent_c, child_a)
        if cycle:
            raise CycleDetectedError("Would create cycle", cycle)
    """
    from db.schema.task_dependencies import TaskDependency
    
    # Build adjacency list from database
    # We need to find if there's a path from child_task_id to parent_task_id
    # Because if child can reach parent, then parent -> child creates a cycle
    
    # Get all dependencies
    result = await session.execute(
        select(TaskDependency.parent_task_id, TaskDependency.child_task_id)
    )
    dependencies = result.fetchall()
    
    # Build adjacency list: task_id -> list of tasks it depends on (its children)
    # For cycle detection, we need to traverse from child_task_id to see if we can reach parent_task_id
    # So we build: task -> tasks that depend on it (reverse direction for DFS)
    adjacency: Dict[UUID, List[UUID]] = defaultdict(list)
    
    for row in dependencies:
        adj_parent, adj_child = row
        # parent_task_id -> child_task_id means "child depends on parent"
        # For DFS from child to find parent, we need: parent -> [children who depend on it]
        adjacency[adj_parent].append(adj_child)
    
    # DFS to check if there's a path from child_task_id to parent_task_id
    visited: Set[UUID] = set()
    path: List[UUID] = []
    
    def dfs(current: UUID, target: UUID) -> Optional[List[UUID]]:
        """DFS helper to find path from current to target."""
        if current in visited:
            return None
        
        visited.add(current)
        path.append(current)
        
        if current == target:
            return list(path)
        
        for neighbor in adjacency.get(current, []):
            result = dfs(neighbor, target)
            if result:
                return result
        
        path.pop()
        return None
    
    # Check if there's a path from child to parent
    # If so, adding parent -> child creates a cycle
    cycle_path = dfs(child_task_id, parent_task_id)
    
    if cycle_path:
        # The cycle would be: parent_task_id -> child_task_id -> ... -> parent_task_id
        # We found: child_task_id -> ... -> parent_task_id
        # So the full cycle is: parent_task_id -> [child_task_id -> ... -> parent_task_id]
        return [parent_task_id] + cycle_path
    
    return None


async def get_ancestors(
    session: AsyncSession,
    task_id: UUID,
) -> Set[UUID]:
    """Get all ancestor tasks (tasks this task depends on, directly or indirectly).
    
    Uses BFS to traverse the dependency graph upward.
    
    Args:
        session: AsyncSession for database queries.
        task_id: The task ID to find ancestors for.
        
    Returns:
        Set of ancestor task IDs.
    """
    from db.schema.task_dependencies import TaskDependency
    
    ancestors: Set[UUID] = set()
    queue: List[UUID] = [task_id]
    
    while queue:
        current = queue.pop(0)
        
        # Find all direct dependencies (tasks this task depends on)
        result = await session.execute(
            select(TaskDependency.parent_task_id).where(
                TaskDependency.child_task_id == current
            )
        )
        parents = [row[0] for row in result.fetchall()]
        
        for parent_id in parents:
            if parent_id not in ancestors:
                ancestors.add(parent_id)
                queue.append(parent_id)
    
    return ancestors


async def get_descendants(
    session: AsyncSession,
    task_id: UUID,
) -> Set[UUID]:
    """Get all descendant tasks (tasks that depend on this task, directly or indirectly).
    
    Uses BFS to traverse the dependency graph downward.
    
    Args:
        session: AsyncSession for database queries.
        task_id: The task ID to find descendants for.
        
    Returns:
        Set of descendant task IDs.
    """
    from db.schema.task_dependencies import TaskDependency
    
    descendants: Set[UUID] = set()
    queue: List[UUID] = [task_id]
    
    while queue:
        current = queue.pop(0)
        
        # Find all tasks that depend on this task
        result = await session.execute(
            select(TaskDependency.child_task_id).where(
                TaskDependency.parent_task_id == current
            )
        )
        children = [row[0] for row in result.fetchall()]
        
        for child_id in children:
            if child_id not in descendants:
                descendants.add(child_id)
                queue.append(child_id)
    
    return descendants


async def get_dependency_order(
    session: AsyncSession,
    task_ids: List[UUID],
) -> List[UUID]:
    """Get tasks in dependency order (topological sort).
    
    Returns tasks sorted such that all dependencies come before
    the tasks that depend on them.
    
    Args:
        session: AsyncSession for database queries.
        task_ids: List of task IDs to sort.
        
    Returns:
        List of task IDs in dependency order.
        
    Raises:
        CycleDetectedError: If a cycle is detected in the dependencies.
    """
    from db.schema.task_dependencies import TaskDependency
    
    if not task_ids:
        return []
    
    task_set = set(task_ids)
    
    # Get all dependencies among the given tasks
    result = await session.execute(
        select(TaskDependency.parent_task_id, TaskDependency.child_task_id).where(
            TaskDependency.parent_task_id.in_(task_ids),
            TaskDependency.child_task_id.in_(task_ids),
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


async def validate_new_dependency(
    session: AsyncSession,
    parent_task_id: UUID,
    child_task_id: UUID,
) -> None:
    """Validate that a new dependency can be safely added.
    
    Checks:
    1. No self-reference (parent != child)
    2. No cycle would be created
    
    Args:
        session: AsyncSession for database queries.
        parent_task_id: The proposed parent task ID.
        child_task_id: The proposed child task ID.
        
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
    cycle_path = await detect_cycle(session, parent_task_id, child_task_id)
    if cycle_path:
        cycle_str = " -> ".join(str(tid) for tid in cycle_path)
        raise CycleDetectedError(
            f"Adding dependency would create a cycle: {cycle_str}",
            cycle_path
        )