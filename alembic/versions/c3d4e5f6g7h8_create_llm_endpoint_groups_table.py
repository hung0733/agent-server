"""create llm_endpoint_groups table

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create llm_endpoint_groups table with proper constraints and indexes."""
    # Create llm_endpoint_groups table
    op.create_table(
        'llm_endpoint_groups',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'user_id', name='uq_llm_endpoint_groups_name_per_user')
    )
    
    # Create indexes for llm_endpoint_groups
    with op.batch_alter_table('llm_endpoint_groups', schema=None) as batch_op:
        batch_op.create_index('idx_llm_endpoint_groups_user', ['user_id'], unique=False)
        # Create partial unique index for is_default (only one default per user)
        # Note: Alembic doesn't support postgresql_where directly in create_index,
        # so we use raw SQL for the partial unique index
        batch_op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_endpoint_groups_default
            ON llm_endpoint_groups(user_id)
            WHERE is_default = true
        """)


def downgrade() -> None:
    """Drop llm_endpoint_groups table."""
    # Drop the partial unique index
    with op.batch_alter_table('llm_endpoint_groups', schema=None) as batch_op:
        batch_op.execute("DROP INDEX IF EXISTS idx_llm_endpoint_groups_default")
        batch_op.drop_index('idx_llm_endpoint_groups_user')
    
    op.drop_table('llm_endpoint_groups')
