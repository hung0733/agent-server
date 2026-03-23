"""DAO (Data Access Object) layer - Database access abstraction.

This layer provides a clean interface for database operations, hiding
SQLAlchemy implementation details from the rest of the application.
All database access should go through DAO methods.

Architecture:
    - Static methods for CRUD operations
    - Returns DTOs, not entities
    - Handles session management internally
    - Async/await compatible

Example:
    from src.db.dao import UserDAO
    
    # All database access through DAO
    user = await UserDAO.get_by_id(1)
    await UserDAO.create(user_dto)
    await UserDAO.update(user_dto)
    await UserDAO.delete(user_id)
"""

from .agent_capability_dao import AgentCapabilityDAO
from .agent_instance_dao import AgentInstanceDAO
from .agent_message_dao import AgentMessageDAO
from .agent_type_dao import AgentTypeDAO
from .api_key_dao import APIKeyDAO
from .audit_dao import AuditLogDAO
from .collaboration_session_dao import CollaborationSessionDAO
from .dead_letter_queue_dao import DeadLetterQueueDAO
from .llm_endpoint_dao import LLMEndpointDAO
from .llm_endpoint_group_dao import LLMEndpointGroupDAO
from .llm_level_endpoint_dao import LLMLevelEndpointDAO
from .task_dao import TaskDAO, TaskDependencyDAO, CycleDetectedError
from .task_queue_dao import TaskQueueDAO
from .task_schedule_dao import TaskScheduleDAO
from .token_usage_dao import TokenUsageDAO
from .tool_call_dao import ToolCallDAO
from .tool_dao import ToolDAO
from .tool_version_dao import ToolVersionDAO
from .user_dao import UserDAO

__all__ = [
    "AgentCapabilityDAO",
    "AgentInstanceDAO",
    "AgentMessageDAO",
    "AgentTypeDAO",
    "APIKeyDAO",
    "AuditLogDAO",
    "CollaborationSessionDAO",
    "CycleDetectedError",
    "DeadLetterQueueDAO",
    "LLMEndpointDAO",
    "LLMEndpointGroupDAO",
    "LLMLevelEndpointDAO",
    "TaskDAO",
    "TaskDependencyDAO",
    "TaskQueueDAO",
    "TaskScheduleDAO",
    "TokenUsageDAO",
    "ToolCallDAO",
    "ToolDAO",
    "ToolVersionDAO",
    "UserDAO",
]
