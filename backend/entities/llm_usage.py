from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    llm_endpoint_id: Mapped[int] = mapped_column(ForeignKey("llm_endpoint.id"), nullable=False, index=True)
    date_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    total_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    in_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    out_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    llm_endpoint = relationship("LlmEndpoint", back_populates="usages")
