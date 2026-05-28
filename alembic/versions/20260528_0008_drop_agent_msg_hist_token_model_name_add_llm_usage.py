"""drop agent_msg_hist token/model_name, add llm_usage table, llm_endpoint user_id nullable

Revision ID: 20260528_0008
Revises: 20260526_0007
Create Date: 2026-05-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260528_0008"
down_revision: str | None = "20260526_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("agent_msg_hist", "token")
    op.drop_column("agent_msg_hist", "model_name")

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("llm_endpoint_id", sa.Integer(), nullable=False),
        sa.Column("date_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("total_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("out_token", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["llm_endpoint_id"], ["llm_endpoint.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_usage_llm_endpoint_id"), "llm_usage", ["llm_endpoint_id"], unique=False)
    op.create_index(op.f("ix_llm_usage_date_time"), "llm_usage", ["date_time"], unique=False)

    op.alter_column("llm_endpoint", "user_id", nullable=True)


def downgrade() -> None:
    op.alter_column("llm_endpoint", "user_id", nullable=False)

    op.drop_index(op.f("ix_llm_usage_date_time"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_llm_endpoint_id"), table_name="llm_usage")
    op.drop_table("llm_usage")

    op.add_column("agent_msg_hist", sa.Column("model_name", sa.String(length=255), nullable=True))
    op.add_column("agent_msg_hist", sa.Column("token", sa.Integer(), nullable=True))
