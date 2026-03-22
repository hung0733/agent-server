"""create task_dependencies table

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-03-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, Sequence[str], None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create task_dependencies table with constraints, foreign keys, and indexes."""
    # Create task_dependencies table
    op.create_table(
        'task_dependencies',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('parent_task_id', sa.UUID(), nullable=False),
        sa.Column('child_task_id', sa.UUID(), nullable=False),
        sa.Column('dependency_type', sa.String(50), server_default='sequential', nullable=False),
        sa.Column('condition_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['parent_task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['child_task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Check constraint to prevent self-reference
        sa.CheckConstraint(
            "parent_task_id != child_task_id",
            name='ck_task_dependencies_no_self_reference'
        ),
    )
    
    # Create unique constraint for (parent_task_id, child_task_id)
    op.create_unique_constraint(
        'uq_task_dependencies_parent_child',
        'task_dependencies',
        ['parent_task_id', 'child_task_id']
    )
    
    # Create indexes for efficient dependency queries
    op.create_index('idx_deps_parent', 'task_dependencies', ['parent_task_id'], unique=False)
    op.create_index('idx_deps_child', 'task_dependencies', ['child_task_id'], unique=False)


def downgrade() -> None:
    """Drop task_dependencies table and associated indexes."""
    # Drop table (will drop indexes and constraints automatically)
    op.drop_table('task_dependencies')