"""create task_schedules table

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-03-22 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, Sequence[str], None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create task_schedules table with proper constraints, foreign keys, and indexes."""
    # Create task_schedules table
    op.create_table(
        'task_schedules',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('task_template_id', sa.UUID(), nullable=False),
        sa.Column('schedule_type', sa.String(50), server_default='cron', nullable=False),
        sa.Column('schedule_expression', sa.Text(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_template_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Check constraint for schedule_type enum
        sa.CheckConstraint(
            "schedule_type IN ('once', 'interval', 'cron')",
            name='ck_task_schedules_schedule_type'
        ),
        # Validation for cron format: 5 space-separated parts
        sa.CheckConstraint(
            r"""CASE 
                WHEN schedule_type = 'cron' THEN
                    schedule_expression ~ '^(\*|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*|\*/[0-9]+)( +(\*|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*|\*/[0-9]+)){4}$'
                ELSE TRUE
            END""",
            name='ck_task_schedules_cron_format'
        ),
        # Validation for interval format: ISO 8601 duration
        sa.CheckConstraint(
            r"""CASE 
                WHEN schedule_type = 'interval' THEN
                    schedule_expression ~ '^P(\\d+Y)?(\\d+M)?(\\d+D)?(T(\\d+H)?(\\d+M)?(\\d+S)?)?$|^P\\d+W$'
                ELSE TRUE
            END""",
            name='ck_task_schedules_interval_format'
        ),
        # Validation for once format: ISO 8601 timestamp
        sa.CheckConstraint(
            r"""CASE 
                WHEN schedule_type = 'once' THEN
                    schedule_expression ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
                ELSE TRUE
            END""",
            name='ck_task_schedules_once_format'
        ),
        # Unique constraint on task_template_id (one schedule per task)
        sa.UniqueConstraint(
            'task_template_id',
            name='uq_task_schedules_template'
        ),
    )
    
    # Create indexes for task_schedules
    with op.batch_alter_table('task_schedules', schema=None) as batch_op:
        # Index on task_template_id for FK joins
        batch_op.create_index('ix_task_schedules_task_template_id', ['task_template_id'], unique=False)
    
    # Create partial index for next_run_at (only active schedules with non-NULL next_run_at)
    # This optimizes queries for schedules ready to execute
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedules_next_run
        ON task_schedules(next_run_at ASC)
        WHERE is_active = true AND next_run_at IS NOT NULL
    """)


def downgrade() -> None:
    """Drop task_schedules table and associated indexes."""
    # Drop partial index first
    op.execute("DROP INDEX IF EXISTS idx_schedules_next_run")
    
    # Drop task_schedules table (will drop indexes and constraints automatically)
    op.drop_table('task_schedules')
