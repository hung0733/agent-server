from sqlalchemy import Boolean, Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import declarative_base, relationship
Base = declarative_base()

class AgentModel(Base):
    __tablename__ = "agent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    sys_prompt = Column(Text, nullable=True)
    
    # 修正 1：分開命名屬性，唔好重複用 messages
    messages = relationship("MessageModel", back_populates="agent", cascade="all, delete-orphan")
    sessions = relationship("SessionModel", back_populates="agent", cascade="all, delete-orphan")
    
class SessionModel(Base):
    __tablename__ = "session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agent.id"), nullable=False)
    session_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)

    # 反向關聯
    agent = relationship("AgentModel", back_populates="sessions")
    messages = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")
    
class MessageModel(Base):
    __tablename__ = "message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agent.id"), nullable=False)
    step_id = Column(String(100), nullable=False)
    msg_id = Column(String(100), nullable=False)
    msg_type = Column(String(50), nullable=False)
    
    create_date = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    is_think_mode = Column(Boolean, nullable=False)
    sent_by = Column(String(20), nullable=False)
    
    session_id = Column(Integer, ForeignKey("session.id"), nullable=False)

    # 修正 2：確保反向關聯嘅屬性名稱同 Model 定義一致
    agent = relationship("AgentModel", back_populates="messages")
    session = relationship("SessionModel", back_populates="messages") # 呢度要對應 SessionModel 嘅 messages