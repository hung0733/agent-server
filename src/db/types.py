# pyright: reportMissingImports=false
"""
Database types and enums for agent-server.

This module defines reusable enum types for database models using StrEnum
for proper JSON serialization with Pydantic v2.
"""
from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class AgentStatus(StrEnum):
    """
    Lifecycle status for an agent instance.
    
    Used to track the operational state of agents in the system.
    String values ensure proper JSON serialization.
    """

    idle = "idle"
    """Agent is available and waiting for tasks."""

    busy = "busy"
    """Agent is currently executing a task."""

    error = "error"
    """Agent encountered an error and is not accepting tasks."""

    offline = "offline"
    """Agent is disconnected or unavailable."""


class TaskStatus(StrEnum):
    """
    Execution status for a task.
    
    Tracks the progress of tasks through their lifecycle.
    String values ensure proper JSON serialization.
    """

    pending = "pending"
    """Task is queued and waiting to be executed."""

    running = "running"
    """Task is currently being executed."""

    completed = "completed"
    """Task finished successfully."""

    failed = "failed"
    """Task execution failed."""

    cancelled = "cancelled"
    """Task was cancelled before completion."""


class Priority(StrEnum):
    """
    Task priority levels.
    
    Determines the order in which tasks are scheduled for execution.
    String values ensure proper JSON serialization.
    """

    low = "low"
    """Low priority - execute when resources are available."""

    normal = "normal"
    """Normal/default priority - standard scheduling."""

    high = "high"
    """High priority - execute before normal tasks."""

    critical = "critical"
    """Critical priority - execute immediately, preempt if necessary."""


class DependencyType(StrEnum):
    """
    Types of task dependencies.
    
    Defines how tasks relate to each other in a workflow.
    String values ensure proper JSON serialization.
    """

    sequential = "sequential"
    """Tasks must execute one after another in order."""

    parallel = "parallel"
    """Tasks can execute concurrently without dependencies."""

    conditional = "conditional"
    """Task execution depends on the outcome of another task."""


class ScheduleType(StrEnum):
    """
    Types of task schedules.
    
    Defines the format and validation rules for schedule expressions.
    String values ensure proper JSON serialization.
    """

    once = "once"
    """One-time schedule at a specific timestamp (ISO 8601)."""

    interval = "interval"
    """Recurring schedule based on time interval (ISO 8601 duration)."""

    cron = "cron"
    """Recurring schedule based on cron expression (5-part unix format)."""


class ActorType(StrEnum):
    """
    Type of actor performing an action in audit logs.
    
    Identifies whether an action was performed by a user, agent, or system.
    String values ensure proper JSON serialization.
    """

    user = "user"
    """Action performed by a human user."""

    agent = "agent"
    """Action performed by an automated agent."""

    system = "system"
    """Action performed by the system itself."""


def gen_random_uuid() -> UUID:
    """
    Generate a random UUID v4.
    
    This function is designed to be used as a field default factory
    for Pydantic models that need UUID fields.
    
    Returns:
        A UUID v4 object.
    """
    return uuid.uuid4()
