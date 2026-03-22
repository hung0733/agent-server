"""create agent_types and agent_instances tables

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-22 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent_types and agent_instances tables with proper constraints and indexes."""
    # Create agent_types table
    op.create_table(
        'agent_types',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_agent_types_name')
    )
    
    # Create indexes for agent_types
    with op.batch_alter_table('agent_types', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_types_name'), ['name'], unique=True)
        batch_op.create_index('idx_agent_types_is_active', ['is_active'], unique=False)
    
    # Create agent_instances table
    op.create_table(
        'agent_instances',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_type_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), server_default='idle', nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('idle', 'busy', 'error', 'offline')",
            name='ck_agent_instances_status'
        )
    )
    
    # Create indexes for agent_instances
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_instances_agent_type_id'), ['agent_type_id'], unique=False)
        batch_op.create_index('idx_agent_instances_status', ['status'], unique=False)
        batch_op.create_index('idx_agent_instances_user', ['user_id'], unique=False)


def downgrade() -> None:
    """Drop agent_instances and agent_types tables."""
    # Drop agent_instances table (will drop indexes automatically)
    op.drop_table('agent_instances')
    
    # Drop agent_types table (will drop indexes automatically)
    with op.batch_alter_table('agent_types', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_types_name'))
        batch_op.drop_index('idx_agent_types_is_active')
    
    op.drop_table('agent_types')
