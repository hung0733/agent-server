"""merge_heads

Revision ID: 6e2241c2c7f2
Revises: d8022d08a7f4, k1l2m3n4o5p6
Create Date: 2026-03-22 18:32:54.813196

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e2241c2c7f2'
down_revision: Union[str, Sequence[str], None] = ('d8022d08a7f4', 'k1l2m3n4o5p6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
