"""create_mcp_tools_table

Revision ID: 28ec04fc51ff
Revises: 4aa1b7c9818c
Create Date: 2026-03-22 21:01:43.862831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '28ec04fc51ff'
down_revision: Union[str, Sequence[str], None] = '4aa1b7c9818c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create mcp_tools table for MCP tools mapping."""
    # Create mcp_tools table
    op.create_table(
        'mcp_tools',
        # Primary key
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        
        # Foreign keys
        sa.Column('mcp_client_id', sa.UUID(), nullable=False),
        sa.Column('tool_id', sa.UUID(), nullable=False),
        
        # MCP tool info
        sa.Column('mcp_tool_name', sa.Text(), nullable=False),
        sa.Column('mcp_tool_description', sa.Text(), nullable=True),
        sa.Column('mcp_tool_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        
        # Control/Tracking
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_invoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invocation_count', sa.Integer(), server_default='0', nullable=True),
        
        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['mcp_client_id'], ['mcp_clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id']),
        sa.UniqueConstraint('mcp_client_id', 'tool_id', name='uq_mcp_tools_client_tool')
    )
    
    # Create indexes for mcp_tools
    with op.batch_alter_table('mcp_tools', schema=None) as batch_op:
        batch_op.create_index('idx_mcp_tools_client', ['mcp_client_id'], unique=False)
        batch_op.create_index('idx_mcp_tools_tool', ['tool_id'], unique=False)
        batch_op.create_index('idx_mcp_tools_active', ['is_active'], unique=False)
        batch_op.create_index('idx_mcp_tools_name', ['mcp_tool_name'], unique=False)


def downgrade() -> None:
    """Drop mcp_tools table."""
    # Drop mcp_tools table (will drop indexes and constraints automatically)
    op.drop_table('mcp_tools')
