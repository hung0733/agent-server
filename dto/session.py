from db.models import SessionModel


class SessionDTO:
    """Session 數據傳輸對象"""
    id: int                    # DB primary key (int)
    agent_id: int              # Foreign key to AgentModel.id
    session_id: str            # Unique identifier within agent
    name: str                  # Display name
    
    def __init__(
        self,
        id: int,
        agent_id: int,
        session_id: str,
        name: str
    ) -> None:
        self.id = id
        self.agent_id = agent_id
        self.session_id = session_id
        self.name = name
    
    @classmethod
    def from_model(cls, model: SessionModel) -> 'SessionDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=model.id,
            agent_id=model.agent_id,
            session_id=model.session_id,
            name=model.name
        )
    
    @classmethod
    def to_create_payload(cls, agent_id: int, session_id: str, name: str) -> dict:
        """創建 payload"""
        return {"agent_id": agent_id, "session_id": session_id, "name": name}