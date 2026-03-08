from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class AgentModel(Base):
    __tablename__ = "agent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    sys_prompt = Column(Text, nullable=True)
    brain_slot_id = Column(Integer, nullable=False)
    sum_slot_id = Column(Integer, nullable=False)