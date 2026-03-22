"""create checkpoints table

Revision ID: 5e35608c04b5
Revises: c4dc949a9791
Create Date: 2026-03-22 21:08:19.990842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5e35608c04b5'
down_revision: Union[str, Sequence[str], None] = 'c4dc949a9791'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create checkpoints table for LangGraph state persistence.
    
    This table stores checkpoint data for conversational threads,
    supporting backtracking and state recovery in LangGraph agents.
    """
    op.create_table(
        'checkpoints',
        sa.Column('thread_id', sa.Text(), nullable=False),
        sa.Column('checkpoint_ns', sa.Text(), nullable=False, server_default=''),
        sa.Column('checkpoint_id', sa.Text(), nullable=False),
        sa.Column('parent_checkpoint_id', sa.Text(), nullable=True),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id',
                                name='pk_checkpoints_composite')
    )
    
    with op.batch_alter_table('checkpoints', schema=None) as batch_op:
        batch_op.create_index('idx_checkpoints_thread_id', ['thread_id'], unique=False)
        batch_op.create_index('idx_checkpoints_parent', ['parent_checkpoint_id'], unique=False)


def downgrade() -> None:
    op.drop_table('checkpoints')
