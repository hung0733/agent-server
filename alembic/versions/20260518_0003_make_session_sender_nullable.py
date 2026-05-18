"""make session sender nullable

Revision ID: 20260518_0003
Revises: 20260515_0002
Create Date: 2026-05-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260518_0003"
down_revision: str | None = "20260515_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "session",
        "sender_agent_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.execute(
        sa.text(
            'update "session" '
            "set sender_agent_id = null "
            "where sender_agent_id = recv_agent_id"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            'update "session" '
            "set sender_agent_id = recv_agent_id "
            "where sender_agent_id is null"
        )
    )
    op.alter_column(
        "session",
        "sender_agent_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
