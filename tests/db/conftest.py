# pyright: reportMissingImports=false
"""
Pytest configuration for database tests.

This module ensures all schema modules are imported before tests run,
which is necessary for SQLAlchemy relationship resolution.
"""
from __future__ import annotations

# Import all schema modules to ensure SQLAlchemy can resolve relationships
from db.schema import users  # noqa: F401
from db.schema import agents  # noqa: F401
from db.schema import llm_endpoints  # noqa: F401
from db.schema import audit  # noqa: F401
from db.schema import agent_capabilities  # noqa: F401
from db.schema import tasks  # noqa: F401
from db.schema import task_dependencies  # noqa: F401
from db.schema import task_schedules  # noqa: F401
from db.schema import task_queue  # noqa: F401
from db.schema import dead_letter_queue  # noqa: F401
from db.schema import collaboration  # noqa: F401
from db.schema import tools  # noqa: F401
from db.schema import token_usage  # noqa: F401
from db.schema import tool_calls  # noqa: F401
