from datetime import datetime
from db.models import AgentModel


class AgentDTO:
    """Agent 數據傳輸對象"""
    id: int                    # DB primary key (int)
    agent_id: str              # Unique identifier (e.g., "agent-uuid")
    name: str                  # Display name
    sys_prompt: str | None     # System prompt
    
    def __init__(
        self,
        id: int,
        agent_id: str,
        name: str,
        sys_prompt: str | None = None
    ) -> None:
        self.id = id
        self.agent_id = agent_id
        self.name = name
        self.sys_prompt = sys_prompt
    
    @classmethod
    def from_model(cls, model: AgentModel) -> 'AgentDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=model.id,
            agent_id=model.agent_id,
            name=model.name,
            sys_prompt=model.sys_prompt
        )
    
    @classmethod
    def to_create_payload(cls, name: str, sys_prompt: str | None) -> dict:
        """創建 payload"""
        return {"name": name, "sys_prompt": sys_prompt}