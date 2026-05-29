from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class AssignedTask(Base):
    __tablename__ = "assigned_task"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_acc.id"), nullable=False, index=True)
    responsible_agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("session.id"), nullable=True, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="brainstorm_pending",
        server_default="brainstorm_pending",
    )
    approved_plan_html: Mapped[str | None] = mapped_column(Text)
    create_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("UserAcc")
    responsible_agent = relationship("Agent", foreign_keys=[responsible_agent_id])
    session = relationship("AgentSession")
    steps = relationship("AssignedTaskStep", back_populates="task", cascade="all, delete-orphan")


class AssignedTaskStep(Base):
    __tablename__ = "assigned_task_step"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    step_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("assigned_task.id"), nullable=False, index=True)
    parent_step_id: Mapped[int | None] = mapped_column(ForeignKey("assigned_task_step.id"), nullable=True, index=True)
    step_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    assign_agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("session.id"), nullable=True, index=True)
    output_html: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[str | None] = mapped_column(Text)
    create_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    task = relationship("AssignedTask", back_populates="steps")
    parent_step = relationship("AssignedTaskStep", remote_side=[id])
    assign_agent = relationship("Agent", foreign_keys=[assign_agent_id])
    session = relationship("AgentSession")
