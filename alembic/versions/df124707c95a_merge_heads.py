"""merge heads

Revision ID: df124707c95a
Revises: a9f3e1b2c8d7, m3n4o5p6q7r8
Create Date: 2026-03-27 09:22:06.407259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'df124707c95a'
down_revision: Union[str, Sequence[str], None] = ('a9f3e1b2c8d7', 'm3n4o5p6q7r8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
