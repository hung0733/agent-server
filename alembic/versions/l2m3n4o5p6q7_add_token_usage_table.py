"""add token_usage table

Revision ID: l2m3n4o5p6q7
Revises: j0k1l2m3n4o5
Create Date: 2026-03-22 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, Sequence[str], None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create token_usage table with proper constraints and indexes."""
    # Create token_usage table
    op.create_table(
        'token_usage',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('model_name', sa.Text(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('estimated_cost_usd', sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_instances.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for token_usage
    # Note: Must use batch_alter_table for creating indexes on new table
    with op.batch_alter_table('token_usage', schema=None) as batch_op:
        batch_op.create_index('idx_token_usage_user_created', ['user_id', 'created_at'], unique=False)
        batch_op.create_index('idx_token_usage_session', ['session_id'], unique=False)


def downgrade() -> None:
    """Drop token_usage table."""
    # Drop token_usage table (will drop indexes automatically)
    with op.batch_alter_table('token_usage', schema=None) as batch_op:
        batch_op.drop_index('idx_token_usage_user_created')
        batch_op.drop_index('idx_token_usage_session')
    
    op.drop_table('token_usage')
