"""create checkpoint_writes table

Revision ID: 93c9d5db432c
Revises: 30f63dfb1e5c
Create Date: 2026-03-22 21:16:45.540918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '93c9d5db432c'
down_revision: Union[str, Sequence[str], None] = '30f63dfb1e5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create checkpoint_writes table for LangGraph write operations tracking.
    
    This table stores checkpoint write operations for conversational threads,
    tracking which channels were written to by which tasks at what order.
    Uses composite primary key for efficient write-ordering operations.
    
    Columns:
    - thread_id: Identifier for the conversational thread
    - checkpoint_ns: Checkpoint namespace for organizing checkpoints (default '')
    - checkpoint_id: Checkpoint identifier for this write operation
    - task_id: Identifies the specific task being tracked
    - idx: Index for ordering writes within a task
    - channel: Which channel this write applies to
    - type: Type of data being written
    - blob: Optionally stores larger write data in binary format (BYTEA)
    - created_at: Timestamp when written
    """
    op.create_table(
        'checkpoint_writes',
        sa.Column('thread_id', sa.Text(), nullable=False),
        sa.Column('checkpoint_ns', sa.Text(), nullable=False, server_default=''),
        sa.Column('checkpoint_id', sa.Text(), nullable=False),
        sa.Column('task_id', sa.Text(), nullable=False),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('blob', postgresql.BYTEA(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id', 'task_id', 'idx',
                                name='pk_checkpoint_writes_composite')
    )
    
    with op.batch_alter_table('checkpoint_writes', schema=None) as batch_op:
        batch_op.create_index('idx_checkpoint_writes_thread_id', ['thread_id'], unique=False)
        batch_op.create_index('idx_checkpoint_writes_checkpoint_id', ['checkpoint_id'], unique=False)


def downgrade() -> None:
    """Drop checkpoint_writes table and all associated constraints/indexes."""
    op.drop_table('checkpoint_writes')
