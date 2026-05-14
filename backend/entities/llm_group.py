from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class LlmGroup(Base):
    __tablename__ = "llm_group"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_acc.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    user = relationship("UserAcc", back_populates="llm_groups")
    agents = relationship("Agent", back_populates="llm_group")
    levels = relationship("LlmLevel", back_populates="llm_group")
