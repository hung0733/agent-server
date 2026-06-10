"""add planned task step json to assigned task

Revision ID: 20260602_0014
Revises: 20260602_0013
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_0014"
down_revision: str | None = "20260602_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assigned_task",
        sa.Column("planned_task_step_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assigned_task", "planned_task_step_json")
