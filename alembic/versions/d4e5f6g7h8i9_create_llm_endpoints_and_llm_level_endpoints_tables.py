"""create llm_endpoints and llm_level_endpoints tables

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-03-22 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create llm_endpoints and llm_level_endpoints tables with proper constraints and indexes."""
    # Create llm_endpoints table
    op.create_table(
        'llm_endpoints',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('base_url', sa.Text(), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('model_name', sa.Text(), nullable=False),
        sa.Column('config_json', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    
    # Create index for llm_endpoints
    with op.batch_alter_table('llm_endpoints', schema=None) as batch_op:
        batch_op.create_index('idx_endpoints_user', ['user_id'], unique=False)
    
    # Create llm_level_endpoints table
    op.create_table(
        'llm_level_endpoints',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('group_id', sa.UUID(), nullable=False),
        sa.Column('difficulty_level', sa.SmallInteger(), nullable=False),
        sa.Column('involves_secrets', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('endpoint_id', sa.UUID(), nullable=False),
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['llm_endpoint_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['endpoint_id'], ['llm_endpoints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint_id', name='uq_llm_level_endpoints_endpoint_id'),
        sa.UniqueConstraint(
            'group_id', 'difficulty_level', 'involves_secrets', 'endpoint_id',
            name='uq_llm_level_endpoints_group_level_secrets_endpoint'
        ),
        sa.CheckConstraint(
            'difficulty_level BETWEEN 1 AND 3',
            name='ck_llm_level_endpoints_difficulty_level'
        ),
    )
    
    # Create index for llm_level_endpoints
    with op.batch_alter_table('llm_level_endpoints', schema=None) as batch_op:
        batch_op.create_index('idx_level_endpoints_group', ['group_id'], unique=False)


def downgrade() -> None:
    """Drop llm_level_endpoints and llm_endpoints tables."""
    # Drop llm_level_endpoints table
    with op.batch_alter_table('llm_level_endpoints', schema=None) as batch_op:
        batch_op.drop_index('idx_level_endpoints_group')
    
    op.drop_table('llm_level_endpoints')
    
    # Drop llm_endpoints table
    with op.batch_alter_table('llm_endpoints', schema=None) as batch_op:
        batch_op.drop_index('idx_endpoints_user')
    
    op.drop_table('llm_endpoints')