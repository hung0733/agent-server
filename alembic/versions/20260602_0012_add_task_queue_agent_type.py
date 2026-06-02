"""add task queue and agent type code table

Revision ID: 20260602_0012
Revises: 20260602_0011
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_0012"
down_revision: str | None = "20260602_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_type",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("update_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.execute(
        """
        INSERT INTO agent_type (code, name)
        SELECT DISTINCT agent_type, agent_type
        FROM agent
        WHERE agent_type IS NOT NULL AND agent_type <> ''
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO agent_type (code, name)
        SELECT DISTINCT agent_type, agent_type
        FROM assigned_task_step
        WHERE agent_type IS NOT NULL AND agent_type <> ''
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.add_column("agent", sa.Column("agent_type_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE agent
        SET agent_type_id = agent_type.id
        FROM agent_type
        WHERE agent.agent_type = agent_type.code
        """
    )
    op.alter_column("agent", "agent_type_id", nullable=False)
    op.create_index(op.f("ix_agent_agent_type_id"), "agent", ["agent_type_id"], unique=False)
    op.create_foreign_key("fk_agent_agent_type_id_agent_type", "agent", "agent_type", ["agent_type_id"], ["id"])
    op.drop_column("agent", "agent_type")

    op.add_column("assigned_task_step", sa.Column("agent_type_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE assigned_task_step
        SET agent_type_id = agent_type.id
        FROM agent_type
        WHERE assigned_task_step.agent_type = agent_type.code
        """
    )
    op.alter_column("assigned_task_step", "agent_type_id", nullable=False)
    op.create_index(
        op.f("ix_assigned_task_step_agent_type_id"),
        "assigned_task_step",
        ["agent_type_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_assigned_task_step_agent_type_id_agent_type",
        "assigned_task_step",
        "agent_type",
        ["agent_type_id"],
        ["id"],
    )
    op.drop_column("assigned_task_step", "agent_type")

    op.alter_column(
        "assigned_task_step",
        "assign_agent_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column("assigned_task_step", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "assigned_task_step",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "assigned_task_step_process_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("log", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["step_id"], ["assigned_task_step.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assigned_task_step_process_log_step_id"),
        "assigned_task_step_process_log",
        ["step_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assigned_task_step_process_log_status"),
        "assigned_task_step_process_log",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assigned_task_step_process_log_started_at"),
        "assigned_task_step_process_log",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assigned_task_step_process_log_started_at"), table_name="assigned_task_step_process_log")
    op.drop_index(op.f("ix_assigned_task_step_process_log_status"), table_name="assigned_task_step_process_log")
    op.drop_index(op.f("ix_assigned_task_step_process_log_step_id"), table_name="assigned_task_step_process_log")
    op.drop_table("assigned_task_step_process_log")

    op.drop_column("assigned_task_step", "processing_started_at")
    op.drop_column("assigned_task_step", "next_run_at")
    op.execute(
        """
        UPDATE assigned_task_step
        SET assign_agent_id = assigned_task.responsible_agent_id
        FROM assigned_task
        WHERE assigned_task_step.task_id = assigned_task.id
          AND assigned_task_step.assign_agent_id IS NULL
        """
    )
    op.alter_column(
        "assigned_task_step",
        "assign_agent_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.add_column("assigned_task_step", sa.Column("agent_type", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE assigned_task_step
        SET agent_type = atype.code
        FROM agent_type atype
        WHERE assigned_task_step.agent_type_id = atype.id
        """
    )
    op.alter_column("assigned_task_step", "agent_type", nullable=False)
    op.drop_constraint("fk_assigned_task_step_agent_type_id_agent_type", "assigned_task_step", type_="foreignkey")
    op.drop_index(op.f("ix_assigned_task_step_agent_type_id"), table_name="assigned_task_step")
    op.drop_column("assigned_task_step", "agent_type_id")

    op.add_column("agent", sa.Column("agent_type", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE agent
        SET agent_type = atype.code
        FROM agent_type atype
        WHERE agent.agent_type_id = atype.id
        """
    )
    op.alter_column("agent", "agent_type", nullable=False)
    op.drop_constraint("fk_agent_agent_type_id_agent_type", "agent", type_="foreignkey")
    op.drop_index(op.f("ix_agent_agent_type_id"), table_name="agent")
    op.drop_column("agent", "agent_type_id")

    op.drop_table("agent_type")
