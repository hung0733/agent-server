# pyright: reportMissingImports=false
"""
Pytest configuration for database tests.

This module ensures all entity modules are imported before tests run,
which is necessary for SQLAlchemy relationship resolution.
"""
from __future__ import annotations

# Import all entity modules for SQLAlchemy relationship resolution
from db.entity import user_entity  # noqa: F401
from db.entity import token_usage_entity  # noqa: F401
from db.entity import agent_entity  # noqa: F401
from db.entity import agent_capability_entity  # noqa: F401
from db.entity import task_entity  # noqa: F401
from db.entity import tool_entity  # noqa: F401
from db.entity import tool_call_entity  # noqa: F401
from db.entity import llm_endpoint_entity  # noqa: F401
from db.entity import task_queue_entity  # noqa: F401
from db.entity import task_schedule_entity  # noqa: F401
from db.entity import dead_letter_queue_entity  # noqa: F401
from db.entity import collaboration_entity  # noqa: F401
from db.entity import audit_entity  # noqa: F401