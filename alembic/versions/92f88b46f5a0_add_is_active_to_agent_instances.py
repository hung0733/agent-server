"""add is_active to agent_instances

Revision ID: 92f88b46f5a0
Revises: a2b3c4d5e6f7
Create Date: 2026-04-01 01:50:07.572257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '92f88b46f5a0'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.drop_column('is_active')
