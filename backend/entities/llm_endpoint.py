from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class LlmEndpoint(Base):
    __tablename__ = "llm_endpoint"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user_acc.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    enc_key: Mapped[str | None] = mapped_column(String(1024))
    model_name: Mapped[str | None] = mapped_column(String(255))
    max_token: Mapped[int | None] = mapped_column(Integer)

    user = relationship("UserAcc", back_populates="llm_endpoints")
    levels = relationship("LlmLevel", back_populates="llm_endpoint")
    usages = relationship("LlmUsage", back_populates="llm_endpoint")
