"""create tools and tool_versions tables

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-22 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, Sequence[str], None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tools and tool_versions tables with proper constraints and indexes."""
    # Create tools table
    op.create_table(
        'tools',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_tools_name')
    )
    
    # Create indexes for tools
    with op.batch_alter_table('tools', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tools_name'), ['name'], unique=False)
        batch_op.create_index('idx_tools_is_active', ['is_active'], unique=False)
    
    # Create tool_versions table
    op.create_table(
        'tool_versions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tool_id', sa.UUID(), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('implementation_ref', sa.Text(), nullable=True),
        sa.Column('config_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for tool_versions
    with op.batch_alter_table('tool_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tool_versions_tool_id'), ['tool_id'], unique=False)
        batch_op.create_index('idx_tool_versions_version', ['version'], unique=False)
    
    # Create partial unique index for default version (one default per tool)
    # Must use raw SQL as Alembic doesn't support postgresql_where in create_index
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_versions_default
        ON tool_versions(tool_id)
        WHERE is_default = true
    """)


def downgrade() -> None:
    """Drop tool_versions and tools tables."""
    # Drop the partial unique index first
    op.execute("DROP INDEX IF EXISTS idx_tool_versions_default")
    
    # Drop tool_versions table (will drop indexes automatically)
    with op.batch_alter_table('tool_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tool_versions_tool_id'))
        batch_op.drop_index('idx_tool_versions_version')
    
    op.drop_table('tool_versions')
    
    # Drop tools table (will drop indexes automatically)
    with op.batch_alter_table('tools', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tools_name'))
        batch_op.drop_index('idx_tools_is_active')
    
    op.drop_table('tools')
