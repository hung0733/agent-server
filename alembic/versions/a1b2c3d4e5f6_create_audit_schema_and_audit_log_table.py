"""create audit schema and audit_log table

Revision ID: a1b2c3d4e5f6
Revises: 7f86bcdf9b7c
Create Date: 2026-03-22 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7f86bcdf9b7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create audit schema and audit_log table with proper indexes."""
    # Create audit schema if it doesn't exist
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    
    # Create audit_log table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('actor_type', sa.Enum('user', 'agent', 'system', name='actor_type_enum'), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('resource_type', sa.Text(), nullable=False),
        sa.Column('resource_id', sa.UUID(), nullable=False),
        sa.Column('old_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='audit'
    )
    
    # Create indexes for efficient querying
    # Index on user_id and created_at for user activity queries
    op.execute(
        "CREATE INDEX idx_audit_user_time ON audit.audit_log(user_id, created_at DESC)"
    )
    # Index on resource_type and resource_id for resource history queries
    op.execute(
        "CREATE INDEX idx_audit_resource ON audit.audit_log(resource_type, resource_id)"
    )


def downgrade() -> None:
    """Drop audit_log table and audit schema."""
    # Drop the table (will drop indexes automatically)
    op.drop_table('audit_log', schema='audit')
    
    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS audit.actor_type_enum")
    
    # Drop the schema
    op.execute("DROP SCHEMA IF EXISTS audit")
