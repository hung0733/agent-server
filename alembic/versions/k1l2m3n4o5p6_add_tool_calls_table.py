"""add tool_calls table

Revision ID: k1l2m3n4o5p6
Revises: l2m3n4o5p6q7
Create Date: 2026-03-22 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, Sequence[str], None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tool_calls table with proper constraints and indexes."""
    # Create tool_calls table
    op.create_table(
        'tool_calls',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('tool_id', sa.UUID(), nullable=False),
        sa.Column('tool_version_id', sa.UUID(), nullable=True),
        sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(50), server_default='pending', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tool_version_id'], ['tool_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name='ck_tool_calls_status'
        ),
        sa.CheckConstraint(
            'duration_ms >= 0',
            name='ck_tool_calls_duration_ms'
        )
    )
    
    # Create indexes for tool_calls
    with op.batch_alter_table('tool_calls', schema=None) as batch_op:
        batch_op.create_index('idx_tool_calls_task', ['task_id'], unique=False)
        batch_op.create_index('idx_tool_calls_tool', ['tool_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_tool_version_id'), ['tool_version_id'], unique=False)


def downgrade() -> None:
    """Drop tool_calls table."""
    # Drop indexes first
    with op.batch_alter_table('tool_calls', schema=None) as batch_op:
        batch_op.drop_index('idx_tool_calls_task')
        batch_op.drop_index('idx_tool_calls_tool')
        batch_op.drop_index(batch_op.f('ix_tool_calls_tool_version_id'))
    
    # Drop tool_calls table
    op.drop_table('tool_calls')
