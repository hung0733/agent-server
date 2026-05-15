"""add agent whatsapp instance

Revision ID: 20260515_0002
Revises: 20260514_0001
Create Date: 2026-05-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260515_0002"
down_revision: str | None = "20260514_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("whatsapp_instance", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "whatsapp_instance")
