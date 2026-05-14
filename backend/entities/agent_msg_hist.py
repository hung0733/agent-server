from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class AgentMsgHist(Base):
    __tablename__ = "agent_msg_hist"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    msg_type: Mapped[str] = mapped_column(String(100), nullable=False)
    create_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    content: Mapped[str | None] = mapped_column(Text)
    token: Mapped[int | None] = mapped_column(Integer)
    is_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_analyst: Mapped[int | None] = mapped_column(Integer)
    meta_data: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(255))

    session = relationship("AgentSession", back_populates="messages")
