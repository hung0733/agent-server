"""rename assigned task step type to agent type

Revision ID: 20260602_0011
Revises: 20260529_0010
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260602_0011"
down_revision: str | None = "20260529_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("assigned_task_step", "step_type", new_column_name="agent_type")
    op.execute(
        """
        UPDATE assigned_task_step
        SET agent_type = CASE agent_type
            WHEN 'brainstorm' THEN 'brainstormer'
            WHEN 'planning' THEN 'planner'
            WHEN 'review' THEN 'reviewer'
            ELSE agent_type
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE assigned_task_step
        SET agent_type = CASE agent_type
            WHEN 'brainstormer' THEN 'brainstorm'
            WHEN 'planner' THEN 'planning'
            WHEN 'reviewer' THEN 'review'
            ELSE agent_type
        END
        """
    )
    op.alter_column("assigned_task_step", "agent_type", new_column_name="step_type")
