"""add is_sub_agent to agent_instances

Revision ID: f9a1c2d3e4f5
Revises: df124707c95a
Create Date: 2026-03-28 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9a1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "df124707c95a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_sub_agent boolean flag to agent_instances."""
    with op.batch_alter_table("agent_instances", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_sub_agent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    """Remove is_sub_agent from agent_instances."""
    with op.batch_alter_table("agent_instances", schema=None) as batch_op:
        batch_op.drop_column("is_sub_agent")
