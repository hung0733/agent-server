"""create tasks table

Revision ID: e5f6g7h8i9j0
Revises: c4d5e6f7g8h9
Create Date: 2026-03-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tasks table with proper constraints, foreign keys, and indexes."""
    # Create tasks table
    op.create_table(
        'tasks',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('parent_task_id', sa.UUID(), nullable=True),
        sa.Column('task_type', sa.Text(), nullable=False),
        sa.Column('status', sa.String(50), server_default='pending', nullable=False),
        sa.Column('priority', sa.String(50), server_default='normal', nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_instances.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name='ck_tasks_status'
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name='ck_tasks_priority'
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name='ck_tasks_retry_count'
        ),
        sa.CheckConstraint(
            "max_retries >= 0",
            name='ck_tasks_max_retries'
        )
    )
    
    # Create indexes for tasks
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index('idx_tasks_status', ['status', 'created_at'], unique=False)
        batch_op.create_index('idx_tasks_user', ['user_id', 'created_at'], unique=False)
        batch_op.create_index('idx_tasks_agent', ['agent_id', 'created_at'], unique=False)
        batch_op.create_index('idx_tasks_scheduled', ['scheduled_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_parent_task_id'), ['parent_task_id'], unique=False)
    
    # Create partial index for scheduled tasks (WHERE status = 'pending')
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_pending
        ON tasks(scheduled_at)
        WHERE status = 'pending'
    """)


def downgrade() -> None:
    """Drop tasks table and associated indexes."""
    # Drop partial index first
    op.execute("DROP INDEX IF EXISTS idx_tasks_scheduled_pending")
    
    # Drop tasks table (will drop indexes automatically)
    op.drop_table('tasks')
