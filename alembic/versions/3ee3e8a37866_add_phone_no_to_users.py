"""add_phone_no_to_users

Revision ID: 3ee3e8a37866
Revises: 6e2241c2c7f2
Create Date: 2026-03-22 20:52:55.029813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ee3e8a37866'
down_revision: Union[str, Sequence[str], None] = '6e2241c2c7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add phone_no column to users table.
    
    Adds nullable TEXT column for storing user phone numbers in free-form format.
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone_no', sa.Text(), nullable=True, comment='User phone number in free-form format'))


def downgrade() -> None:
    """Remove phone_no column from users table."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('phone_no')
