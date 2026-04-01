"""add retry tracking to task schedules

Revision ID: 80fe49dcf857
Revises: 92f88b46f5a0
Create Date: 2026-04-01 18:04:02.045775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '80fe49dcf857'
down_revision: Union[str, Sequence[str], None] = '92f88b46f5a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add retry tracking fields to task_schedules."""
    # Add retry tracking fields to task_schedules table
    with op.batch_alter_table('task_schedules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema - remove retry tracking fields from task_schedules."""
    # Remove retry tracking fields from task_schedules table
    with op.batch_alter_table('task_schedules', schema=None) as batch_op:
        batch_op.drop_column('last_failure_at')
        batch_op.drop_column('consecutive_failures')
