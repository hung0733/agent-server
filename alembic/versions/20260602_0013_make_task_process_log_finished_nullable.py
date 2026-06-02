"""make task process log finished_at nullable

Revision ID: 20260602_0013
Revises: 20260602_0012
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_0013"
down_revision: str | None = "20260602_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "assigned_task_step_process_log",
        "finished_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE assigned_task_step_process_log
        SET finished_at = started_at
        WHERE finished_at IS NULL
        """
    )
    op.alter_column(
        "assigned_task_step_process_log",
        "finished_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
