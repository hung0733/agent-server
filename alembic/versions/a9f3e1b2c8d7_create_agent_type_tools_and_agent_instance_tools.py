"""create_agent_type_tools_and_agent_instance_tools

Revision ID: a9f3e1b2c8d7
Revises: c43b015b6f42
Create Date: 2026-03-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a9f3e1b2c8d7'
down_revision: Union[str, Sequence[str], None] = 'c43b015b6f42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent_type_tools and agent_instance_tools tables."""

    # ── agent_type_tools ──────────────────────────────────────────────────────
    op.create_table(
        'agent_type_tools',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_type_id', sa.UUID(), nullable=False),
        sa.Column('tool_id', sa.UUID(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_type_id', 'tool_id', name='uq_agent_type_tools'),
    )
    with op.batch_alter_table('agent_type_tools', schema=None) as batch_op:
        batch_op.create_index('idx_att_agent_type', ['agent_type_id'], unique=False)
        batch_op.create_index('idx_att_tool', ['tool_id'], unique=False)
        batch_op.create_index('idx_att_active', ['is_active'], unique=False)

    # ── agent_instance_tools ──────────────────────────────────────────────────
    op.create_table(
        'agent_instance_tools',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_instance_id', sa.UUID(), nullable=False),
        sa.Column('tool_id', sa.UUID(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('config_override', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_instance_id'], ['agent_instances.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_instance_id', 'tool_id', name='uq_agent_instance_tools'),
    )
    with op.batch_alter_table('agent_instance_tools', schema=None) as batch_op:
        batch_op.create_index('idx_ait_instance', ['agent_instance_id'], unique=False)
        batch_op.create_index('idx_ait_tool', ['tool_id'], unique=False)
        batch_op.create_index('idx_ait_enabled', ['is_enabled'], unique=False)


def downgrade() -> None:
    """Drop agent_type_tools and agent_instance_tools tables."""
    op.drop_table('agent_instance_tools')
    op.drop_table('agent_type_tools')
