"""drop legacy memory schema

Revision ID: 20260521_0005
Revises: 20260521_0004
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260521_0005"
down_revision: str | None = "20260521_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_short_term_mem_session_id"), table_name="short_term_mem")
    op.drop_table("short_term_mem")

    op.drop_index(op.f("ix_memory_block_agent_id"), table_name="memory_block")
    op.drop_table("memory_block")

    op.drop_index(op.f("ix_long_term_mem_agent_id"), table_name="long_term_mem")
    op.drop_table("long_term_mem")

    op.drop_column("agent_msg_hist", "is_analyst")
    op.drop_column("agent_msg_hist", "is_summary")


def downgrade() -> None:
    op.add_column(
        "agent_msg_hist",
        sa.Column("is_summary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("agent_msg_hist", sa.Column("is_analyst", sa.Integer(), nullable=True))

    op.create_table(
        "long_term_mem",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("token", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_long_term_mem_agent_id"), "long_term_mem", ["agent_id"], unique=False)

    op.create_table(
        "memory_block",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("memory_type", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("last_upd_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memory_block_agent_id"), "memory_block", ["agent_id"], unique=False)

    op.create_table(
        "short_term_mem",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("token", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_short_term_mem_session_id"), "short_term_mem", ["session_id"], unique=False)
