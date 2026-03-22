"""create checkpoint_blobs table

Revision ID: 30f63dfb1e5c
Revises: 5e35608c04b5
Create Date: 2026-03-22 21:13:53.487574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '30f63dfb1e5c'
down_revision: Union[str, Sequence[str], None] = '5e35608c04b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create checkpoint_blobs table for LangGraph large checkpoint data storage.
    
    This table stores large binary checkpoint data (blobs) that are too large
    to store inline in the checkpoints table. Uses composite primary key for
    efficient lookup by thread, namespace, channel, and version.
    
    Columns:
    - thread_id: Identifier matching a conversational thread
    - checkpoint_ns: Checkpoint namespace for organizing checkpoints
    - channel: Which channel in the checkpoint this blob belongs to
    - version: Version string for the specific blob
    - type: Blob data type specification
    - blob: Large binary data (BYTEA) for checkpoint artifacts
    - created_at: Timestamp when blob was created
    """
    op.create_table(
        'checkpoint_blobs',
        sa.Column('thread_id', sa.Text(), nullable=False),
        sa.Column('checkpoint_ns', sa.Text(), nullable=False, server_default=''),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('version', sa.Text(), nullable=False),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('blob', postgresql.BYTEA(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'channel', 'version',
                                name='pk_checkpoint_blobs_composite')
    )
    
    with op.batch_alter_table('checkpoint_blobs', schema=None) as batch_op:
        batch_op.create_index('idx_checkpoint_blobs_thread_id', ['thread_id'], unique=False)


def downgrade() -> None:
    """Drop checkpoint_blobs table and all associated constraints/indexes."""
    op.drop_table('checkpoint_blobs')
