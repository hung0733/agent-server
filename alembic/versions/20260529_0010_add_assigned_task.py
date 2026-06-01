"""add assigned task tables

Revision ID: 20260529_0010
Revises: 20260528_0009
Create Date: 2026-05-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260529_0010"
down_revision: str | None = "20260528_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assigned_task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("responsible_agent_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=100), server_default="brainstorm_pending", nullable=False),
        sa.Column("approved_plan_html", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("update_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["responsible_agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_acc.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(op.f("ix_assigned_task_responsible_agent_id"), "assigned_task", ["responsible_agent_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_session_id"), "assigned_task", ["session_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_user_id"), "assigned_task", ["user_id"], unique=False)

    op.create_table(
        "assigned_task_step",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("parent_step_id", sa.Integer(), nullable=True),
        sa.Column("step_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("assign_agent_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("output_html", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("update_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assign_agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["parent_step_id"], ["assigned_task_step.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["assigned_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id"),
    )
    op.create_index(op.f("ix_assigned_task_step_assign_agent_id"), "assigned_task_step", ["assign_agent_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_step_parent_step_id"), "assigned_task_step", ["parent_step_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_step_session_id"), "assigned_task_step", ["session_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_step_task_id"), "assigned_task_step", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_assigned_task_step_task_id"), table_name="assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_step_session_id"), table_name="assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_step_parent_step_id"), table_name="assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_step_assign_agent_id"), table_name="assigned_task_step")
    op.drop_table("assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_user_id"), table_name="assigned_task")
    op.drop_index(op.f("ix_assigned_task_session_id"), table_name="assigned_task")
    op.drop_index(op.f("ix_assigned_task_responsible_agent_id"), table_name="assigned_task")
    op.drop_table("assigned_task")
