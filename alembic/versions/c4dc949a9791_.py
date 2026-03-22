"""create memory_blocks table

Revision ID: c4dc949a9791
Revises: 28ec04fc51ff
Create Date: 2026-03-22 21:04:46.316496

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4dc949a9791'
down_revision: Union[str, Sequence[str], None] = '28ec04fc51ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create memory_blocks table for agent memory storage."""
    # Create memory_blocks table
    op.create_table(
        'memory_blocks',
        # Primary key
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        
        # Foreign key to agent_instances
        sa.Column('agent_instance_id', sa.UUID(), nullable=False),
        
        # Memory type (fixed three types)
        sa.Column('memory_type', sa.Text(), nullable=False),
        
        # Memory content in markdown format
        sa.Column('content', sa.Text(), nullable=False),
        
        # Version control for memories
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        
        # Active memory switch
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_instance_id'], ['agent_instances.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "memory_type IN ('IDENTITY', 'SOUL', 'USER_PROFILE')",
            name='ck_memory_blocks_type'
        ),
        sa.UniqueConstraint('agent_instance_id', 'memory_type', name='uq_memory_blocks_agent_type')
    )
    
    # Create indexes for memory_blocks
    with op.batch_alter_table('memory_blocks', schema=None) as batch_op:
        batch_op.create_index('idx_memory_blocks_agent', ['agent_instance_id'], unique=False)
        batch_op.create_index('idx_memory_blocks_type', ['memory_type'], unique=False)
        batch_op.create_index('idx_memory_blocks_active', ['is_active'], unique=False)


def downgrade() -> None:
    """Drop memory_blocks table."""
    # Drop memory_blocks table (will drop indexes and constraints automatically)
    op.drop_table('memory_blocks')
