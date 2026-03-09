"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create agent table if not exists
    op.create_table('agent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('sys_prompt', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id')
    )
    
    # Create session table if not exists
    op.create_table('session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=100), default='未命名對話'),
        sa.ForeignKeyConstraint(['agent_id'], ['agent.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_unique_constraint(
        'uq_session_agent_session_id', 
        'session', 
        ['agent_id', 'session_id']
    )
    
    # Create message table if not exists
    op.create_table('message',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('step_id', sa.String(length=100), nullable=False),
        sa.Column('msg_id', sa.String(length=100), nullable=False),
        sa.Column('msg_type', sa.String(length=50), nullable=False),
        sa.Column('create_date', sa.DateTime(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sent_by', sa.String(length=20), nullable=False),
        sa.Column('is_think_mode', sa.Boolean(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.Integer(), default=0, nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agent.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['session.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for performance
    op.create_index(
        'idx_message_agent_session', 
        'message', 
        ['agent_id', 'session_id']
    )
    op.create_index('idx_message_step_id', 'message', ['step_id'])


def downgrade() -> None:
    op.drop_index('idx_message_step_id')
    op.drop_index('idx_message_agent_session')
    op.drop_table('message')
    op.drop_table('session')
    op.drop_table('agent')