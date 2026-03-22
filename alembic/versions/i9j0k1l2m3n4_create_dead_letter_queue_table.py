"""create dead_letter_queue table

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-22 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, Sequence[str], None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create dead_letter_queue table with proper constraints, foreign keys, and indexes.
    
    The dead_letter_queue table supports:
    - Preservation of failed task context even if original task deleted
    - Full error details and stack traces for debugging
    - Administrative resolution workflow with audit trail
    - Original payload preservation for potential reprocessing
    
    Foreign key patterns:
    - original_task_id: SET NULL (allows task deletion without losing DLQ record)
    - original_queue_entry_id: CASCADE (queue entries are transient)
    - resolved_by: SET NULL (allows user deletion without breaking DLQ audit trail)
    
    Critical partial indexes:
    - idx_dlq_unresolved: For monitoring active DLQ items (is_active = true)
    - idx_dlq_resolved: For historical review and auditing (resolved_at IS NOT NULL)
    """
    # Create dead_letter_queue table
    op.create_table(
        'dead_letter_queue',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('original_task_id', sa.UUID(), nullable=True),
        sa.Column('original_queue_entry_id', sa.UUID(), nullable=True),
        sa.Column('original_payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=False),
        sa.Column('failure_details_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead_lettered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['original_task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['original_queue_entry_id'], ['task_queue.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        # Check constraint for retry_count validation
        sa.CheckConstraint(
            "retry_count >= 0",
            name='ck_dead_letter_queue_retry_count'
        ),
    )
    
    # Create regular indexes for dead_letter_queue
    with op.batch_alter_table('dead_letter_queue', schema=None) as batch_op:
        batch_op.create_index('ix_dead_letter_queue_original_task_id', ['original_task_id'], unique=False)
        batch_op.create_index('ix_dead_letter_queue_original_queue_entry_id', ['original_queue_entry_id'], unique=False)
        batch_op.create_index('ix_dead_letter_queue_resolved_by', ['resolved_by'], unique=False)
    
    # Create partial index for monitoring active/unresolved DLQ items
    # Most important index for operational monitoring dashboards
    # Only includes items where is_active = true
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dlq_unresolved
        ON dead_letter_queue(created_at DESC)
        WHERE is_active = true
    """)
    
    # Create partial index for resolved items (historical review and auditing)
    # Only includes items that have been resolved (resolved_at IS NOT NULL)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dlq_resolved
        ON dead_letter_queue(resolved_at DESC)
        WHERE resolved_at IS NOT NULL
    """)


def downgrade() -> None:
    """Drop dead_letter_queue table and associated indexes."""
    # Drop partial indexes first
    op.execute("DROP INDEX IF EXISTS idx_dlq_resolved")
    op.execute("DROP INDEX IF EXISTS idx_dlq_unresolved")
    
    # Drop dead_letter_queue table (regular indexes dropped automatically)
    op.drop_table('dead_letter_queue')
