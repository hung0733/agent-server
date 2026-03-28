"""add_agent_status_constraint

Revision ID: f510b5ecbfcb
Revises: df124707c95a
Create Date: 2026-03-28 02:11:20.423291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f510b5ecbfcb'
down_revision: Union[str, Sequence[str], None] = 'df124707c95a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
