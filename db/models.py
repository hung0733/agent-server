from sqlalchemy import Boolean, Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import declarative_base, relationship
Base = declarative_base()

class AgentModel(Base):
    __tablename__ = "agent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    sys_prompt = Column(Text, nullable=True)
    brain_slot_id = Column(Integer, nullable=False)
    sum_slot_id = Column(Integer, nullable=False)
    
    messages = relationship("MessageModel", back_populates="agent", cascade="all, delete-orphan")
    
class MessageModel(Base):
    __tablename__ = "message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agent.id"), nullable=False)
    step_id = Column(String(100), nullable=False)
    msg_id = Column(String(100), nullable=False)
    msg_type = Column(String(50), nullable=False)
    
    create_date = Column(DateTime, server_default=func.now(),nullable=False)
    
    content = Column(Text, nullable=False)
    
    is_think_mode = Column(Boolean, nullable=False)
    sent_by = Column(String(20), nullable=False)

    # 反向關聯
    agent = relationship("AgentModel", back_populates="messages")