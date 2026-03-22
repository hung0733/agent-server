"""create agent_capabilities table

Revision ID: d8022d08a7f4
Revises: d4e5f6g7h8i9
Create Date: 2026-03-22 14:26:55.728312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8022d08a7f4'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent_capabilities table with proper constraints and indexes."""
    op.create_table(
        'agent_capabilities',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_type_id', sa.UUID(), nullable=False),
        sa.Column('capability_name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    with op.batch_alter_table('agent_capabilities', schema=None) as batch_op:
        batch_op.create_index('idx_capabilities_type', ['agent_type_id'], unique=False)
        batch_op.create_index('idx_capabilities_name', ['capability_name'], unique=False)


def downgrade() -> None:
    """Drop agent_capabilities table."""
    # Drop table (indexes are dropped automatically)
    op.drop_table('agent_capabilities')
