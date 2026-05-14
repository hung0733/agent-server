from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class LlmLevel(Base):
    __tablename__ = "llm_level"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    llm_group_id: Mapped[int] = mapped_column(ForeignKey("llm_group.id"), nullable=False, index=True)
    llm_endpoint_id: Mapped[int] = mapped_column(ForeignKey("llm_endpoint.id"), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    llm_group = relationship("LlmGroup", back_populates="levels")
    llm_endpoint = relationship("LlmEndpoint", back_populates="levels")
