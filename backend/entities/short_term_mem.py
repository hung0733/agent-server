from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class ShortTermMem(Base):
    __tablename__ = "short_term_mem"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"), nullable=False, index=True)
    content: Mapped[str | None] = mapped_column(Text)
    create_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    token: Mapped[int | None] = mapped_column(Integer)

    session = relationship("AgentSession", back_populates="short_term_mems")
