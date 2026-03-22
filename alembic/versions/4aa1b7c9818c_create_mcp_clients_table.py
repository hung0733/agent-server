"""create_mcp_clients_table

Revision ID: 4aa1b7c9818c
Revises: b243438ff66f
Create Date: 2026-03-22 20:57:17.968656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4aa1b7c9818c'
down_revision: Union[str, Sequence[str], None] = 'b243438ff66f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create mcp_clients table for MCP client management."""
    # Create mcp_clients table
    op.create_table(
        'mcp_clients',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        
        # Protocol/config fields
        sa.Column('protocol', sa.Text(), nullable=False),
        sa.Column('base_url', sa.Text(), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('headers', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=True),
        
        # Auth config
        sa.Column('auth_type', sa.Text(), nullable=True),
        sa.Column('auth_config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=True),
        
        # Status/Connection
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        
        # Metadata
        sa.Column('client_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "protocol IN ('http', 'websocket')",
            name='ck_mcp_clients_protocol'
        ),
        sa.CheckConstraint(
            "auth_type IN ('none', 'api_key', 'bearer', 'basic', 'oauth2')",
            name='ck_mcp_clients_auth_type'
        ),
        sa.CheckConstraint(
            "status IN ('connected', 'disconnected', 'error')",
            name='ck_mcp_clients_status'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )
    
    # Create indexes for mcp_clients
    with op.batch_alter_table('mcp_clients', schema=None) as batch_op:
        batch_op.create_index('idx_mcp_clients_user', ['user_id'], unique=False)
        batch_op.create_index('idx_mcp_clients_status', ['status'], unique=False)
        batch_op.create_index('idx_mcp_clients_active', ['is_active'], unique=False)


def downgrade() -> None:
    """Drop mcp_clients table."""
    # Drop mcp_clients table (will drop indexes automatically)
    op.drop_table('mcp_clients')
