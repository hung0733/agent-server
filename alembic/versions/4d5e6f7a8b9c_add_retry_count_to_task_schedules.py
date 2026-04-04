"""add retry_count to task_schedules

Revision ID: 4d5e6f7a8b9c
Revises: 07ef83296bf6
Create Date: 2026-04-04 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d5e6f7a8b9c'
down_revision: Union[str, Sequence[str], None] = '07ef83296bf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('task_schedules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_check_constraint('ck_task_schedules_retry_count', 'retry_count >= 0')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('task_schedules', schema=None) as batch_op:
        batch_op.drop_constraint('ck_task_schedules_retry_count', type_='check')
        batch_op.drop_column('retry_count')
