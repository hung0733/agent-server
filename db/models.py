from sqlalchemy import JSON, Boolean, Column, Integer, String, Text, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector
Base = declarative_base()

class AgentModel(Base):
    __tablename__ = "agent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    sys_prompt = Column(Text, nullable=True)
    is_inited = Column(Boolean, default=False)
    
    # 修正 1：分開命名屬性，唔好重複用 messages
    sessions = relationship("SessionModel", back_populates="agent", cascade="all, delete-orphan")
    long_term_memorys = relationship("LongTermMemoryModel", back_populates="agent", cascade="all, delete-orphan")
    memory_blocks = relationship("MemoryBlockModel", back_populates="agent", cascade="all, delete-orphan")
    
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
    step_id = Column(String(100), nullable=False)
    msg_id = Column(String(100), nullable=False)
    msg_type = Column(String(50), nullable=False)
    
    create_date = Column(TIMESTAMP(timezone=True), nullable=False)
    content = Column(Text, nullable=False)
    is_think_mode = Column(Boolean, nullable=False)
    sent_by = Column(String(20), nullable=False)
    
    session_id = Column(Integer, ForeignKey("session.id"), nullable=False)
    
    # 摘要狀態標記
    is_summaryed = Column(Boolean, default=False, nullable=False)
    
    # 分析狀態標記
    is_analysed = Column(Boolean, default=False, nullable=False)
    
    token = Column(Integer, default=0, nullable=False)

    # 移除 agent_id 後，不再需要與 AgentModel 的反向關聯
    session = relationship("SessionModel", back_populates="messages") # 呢度要對應 SessionModel 嘅 messages


class PromptModel(Base):
    __tablename__ = "prompt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_type = Column(String(50), nullable=False)
    prompt = Column(Text, nullable=False)
    retry_prompt = Column(Text, nullable=True)


class LongTermMemoryModel(Base):
    __tablename__ = "long_term_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)  # SERIAL
    agent_id = Column(Integer, ForeignKey("agent.id"), nullable=False)
    content = Column(JSON, nullable=False)  # JSONB in PostgreSQL
    vector_content = Column(Vector(1024), nullable=True)  # vector(1024) - pgvector column
    importance = Column(Integer, default=5)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    
    # 反向關聯
    agent = relationship("AgentModel", back_populates="long_term_memorys")


class MemoryBlockModel(Base):
    __tablename__ = "memory_block"

    id = Column(Integer, primary_key=True, autoincrement=True)  # SERIAL
    agent_id = Column(Integer, ForeignKey("agent.id"), nullable=False)
    block_type = Column(String(20), nullable=False)  # 'soul', 'identity', 'user_profile'
    content = Column(JSON, nullable=False)  # JSONB - 儲存拆解後的文字與細節
    vector_content = Column(Vector(1024), nullable=True)  # vector(1024) - BGE-M3 向量
    is_active = Column(Boolean, default=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    
    # 反向關聯
    agent = relationship("AgentModel", back_populates="memory_blocks")