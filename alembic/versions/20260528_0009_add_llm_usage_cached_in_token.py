"""add llm_usage cached input token

Revision ID: 20260528_0009
Revises: 20260528_0008
Create Date: 2026-05-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260528_0009"
down_revision: str | None = "20260528_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column("cached_in_token", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("llm_usage", "cached_in_token")
