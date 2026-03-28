"""merge agent instance heads

Revision ID: 8301949ee373
Revises: f510b5ecbfcb, f9a1c2d3e4f5
Create Date: 2026-03-28 20:12:04.725088

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8301949ee373'
down_revision: Union[str, Sequence[str], None] = ('f510b5ecbfcb', 'f9a1c2d3e4f5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
