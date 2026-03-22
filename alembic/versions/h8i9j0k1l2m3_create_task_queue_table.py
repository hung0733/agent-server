"""create task_queue table

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-03-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, Sequence[str], None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create task_queue table with proper constraints, foreign keys, and indexes.
    
    The task_queue table supports:
    - Priority-based ordering for task execution
    - Scheduled execution (delayed tasks)
    - Agent claiming for distributed processing
    - Retry logic with configurable max_retries
    - Error tracking and result storage
    
    Critical partial indexes:
    - idx_queue_poll: For efficient polling of pending tasks (priority DESC, scheduled_at ASC)
    - idx_queue_claimed: For tracking active tasks by agent (claimed_by WHERE status = 'running')
    - idx_queue_retry: For monitoring retries (retry_count WHERE status = 'pending')
    """
    # Create task_queue table
    op.create_table(
        'task_queue',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(50), server_default='pending', nullable=False),
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
        sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('claimed_by', sa.UUID(), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['claimed_by'], ['agent_instances.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        # Check constraints for enum and range validation
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name='ck_task_queue_status'
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name='ck_task_queue_retry_count'
        ),
        sa.CheckConstraint(
            "max_retries >= 0",
            name='ck_task_queue_max_retries'
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name='ck_task_queue_priority'
        ),
    )
    
    # Create regular indexes for task_queue
    with op.batch_alter_table('task_queue', schema=None) as batch_op:
        batch_op.create_index('ix_task_queue_task_id', ['task_id'], unique=False)
        batch_op.create_index('ix_task_queue_claimed_by', ['claimed_by'], unique=False)
    
    # Create partial index for queue polling: highest priority, earliest scheduled first
    # Only indexes pending tasks for efficient polling
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_queue_poll
        ON task_queue(priority DESC, scheduled_at ASC)
        WHERE status = 'pending'
    """)
    
    # Create partial index for active task tracking by agent
    # Only indexes running tasks for active task reporting
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_queue_claimed
        ON task_queue(claimed_by)
        WHERE status = 'running'
    """)
    
    # Create partial index for retry monitoring
    # Only indexes pending tasks for retry monitoring
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_queue_retry
        ON task_queue(retry_count)
        WHERE status = 'pending'
    """)


def downgrade() -> None:
    """Drop task_queue table and associated indexes."""
    # Drop partial indexes first
    op.execute("DROP INDEX IF EXISTS idx_queue_retry")
    op.execute("DROP INDEX IF EXISTS idx_queue_claimed")
    op.execute("DROP INDEX IF EXISTS idx_queue_poll")
    
    # Drop task_queue table (will drop regular indexes automatically)
    op.drop_table('task_queue')