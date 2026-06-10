"""add review suggest to assigned task step

Revision ID: 20260610_0015
Revises: 20260602_0014
Create Date: 2026-06-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260610_0015"
down_revision: str | None = "20260602_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assigned_task_step",
        sa.Column("review_suggest", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assigned_task_step", "review_suggest")
