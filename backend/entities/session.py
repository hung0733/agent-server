from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class AgentSession(Base):
    __tablename__ = "session"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recv_agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    session_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), nullable=False, index=True)
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    recv_agent = relationship("Agent", back_populates="recv_sessions", foreign_keys=[recv_agent_id])
    sender_agent = relationship("Agent", back_populates="sent_sessions", foreign_keys=[sender_agent_id])
    messages = relationship("AgentMsgHist", back_populates="session")
    short_term_mems = relationship("ShortTermMem", back_populates="session")
