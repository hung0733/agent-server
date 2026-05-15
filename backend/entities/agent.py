from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_acc.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    llm_group_id: Mapped[int] = mapped_column(ForeignKey("llm_group.id"), nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_sub_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    phone_no: Mapped[str | None] = mapped_column(String(50))
    whatsapp_key: Mapped[str | None] = mapped_column(String(1024))
    whatsapp_instance: Mapped[str | None] = mapped_column(String(255))

    user = relationship("UserAcc", back_populates="agents")
    llm_group = relationship("LlmGroup", back_populates="agents")
    recv_sessions = relationship(
        "AgentSession",
        back_populates="recv_agent",
        foreign_keys="AgentSession.recv_agent_id",
    )
    sent_sessions = relationship(
        "AgentSession",
        back_populates="sender_agent",
        foreign_keys="AgentSession.sender_agent_id",
    )
    long_term_mems = relationship("LongTermMem", back_populates="agent")
    memory_blocks = relationship("MemoryBlock", back_populates="agent")
