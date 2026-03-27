"""
Task scheduling and execution module.

Manages scheduled task execution including:
- Message-based tasks (prompt injection to agents)
- Method-based tasks (static method invocation)

Import path: scheduler
"""
from __future__ import annotations

__all__ = ["TaskExecutor", "TaskScheduler"]
