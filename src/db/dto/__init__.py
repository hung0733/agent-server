"""DTO (Data Transfer Object) layer - Objects for data transfer between layers.

DTOs are used to transfer data between the DAO layer and business logic,
or between the API layer and clients. They provide a clean separation
between database entities and API contracts.

Example:
    from src.db.dto import UserDTO, TaskDTO
    
    # DTOs are returned from DAO methods
    user_dto = await UserDAO.get_by_id(1)
"""

from .user_dto import (
    UserBase,
    UserCreate,
    UserUpdate,
    User,
    APIKeyBase,
    APIKeyCreate,
    APIKeyUpdate,
    APIKey,
)
from .token_usage_dto import (
    TokenUsageBase,
    TokenUsageCreate,
    TokenUsageUpdate,
    TokenUsage,
)
from .agent_capability_dto import (
    AgentCapabilityBase,
    AgentCapabilityCreate,
    AgentCapabilityUpdate,
    AgentCapability,
)
from .task_dto import (
    TaskBase,
    TaskCreate,
    TaskUpdate,
    Task,
    TaskDependencyBase,
    TaskDependencyCreate,
    TaskDependencyUpdate,
    TaskDependency,
)
from .tool_dto import (
    ToolBase,
    ToolCreate,
    ToolUpdate,
    Tool,
    ToolVersionBase,
    ToolVersionCreate,
    ToolVersionUpdate,
    ToolVersion,
)
from .tool_call_dto import (
    ToolCallBase,
    ToolCallCreate,
    ToolCallUpdate,
    ToolCall,
)
from .collaboration_dto import (
    CollaborationSessionBase,
    CollaborationSessionCreate,
    CollaborationSessionUpdate,
    CollaborationSession,
    AgentMessageBase,
    AgentMessageCreate,
    AgentMessageUpdate,
    AgentMessage,
)

__all__ = [
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "User",
    "APIKeyBase",
    "APIKeyCreate",
    "APIKeyUpdate",
    "APIKey",
    "TokenUsageBase",
    "TokenUsageCreate",
    "TokenUsageUpdate",
    "TokenUsage",
    "AgentCapabilityBase",
    "AgentCapabilityCreate",
    "AgentCapabilityUpdate",
    "AgentCapability",
    "TaskBase",
    "TaskCreate",
    "TaskUpdate",
    "Task",
    "TaskDependencyBase",
    "TaskDependencyCreate",
    "TaskDependencyUpdate",
    "TaskDependency",
    "ToolBase",
    "ToolCreate",
    "ToolUpdate",
    "Tool",
    "ToolVersionBase",
    "ToolVersionCreate",
    "ToolVersionUpdate",
    "ToolVersion",
    "ToolCallBase",
    "ToolCallCreate",
    "ToolCallUpdate",
    "ToolCall",
    "CollaborationSessionBase",
    "CollaborationSessionCreate",
    "CollaborationSessionUpdate",
    "CollaborationSession",
    "AgentMessageBase",
    "AgentMessageCreate",
    "AgentMessageUpdate",
    "AgentMessage",
]
