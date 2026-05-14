from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class UserAcc(Base):
    __tablename__ = "user_acc"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phoneno: Mapped[str | None] = mapped_column(String(50))

    agents = relationship("Agent", back_populates="user")
    llm_groups = relationship("LlmGroup", back_populates="user")
    llm_endpoints = relationship("LlmEndpoint", back_populates="user")
