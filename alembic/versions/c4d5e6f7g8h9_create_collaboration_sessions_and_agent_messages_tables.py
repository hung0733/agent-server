"""create collaboration_sessions and agent_messages tables

Revision ID: c4d5e6f7g8h9
Revises: b2c3d4e5f6g7
Create Date: 2026-03-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7g8h9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create collaboration_sessions and agent_messages tables with proper constraints and indexes."""
    # Create collaboration_sessions table
    op.create_table(
        'collaboration_sessions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('main_agent_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('status', sa.String(50), server_default='active', nullable=False),
        sa.Column('involves_secrets', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('context_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['main_agent_id'], ['agent_instances.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', name='uq_collaboration_sessions_session_id'),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'failed', 'cancelled')",
            name='ck_collaboration_sessions_status'
        )
    )
    
    # Create indexes for collaboration_sessions
    with op.batch_alter_table('collaboration_sessions', schema=None) as batch_op:
        batch_op.create_index('idx_collab_user', ['user_id'], unique=False)
        batch_op.create_index('idx_collab_status', ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_sessions_main_agent_id'), ['main_agent_id'], unique=False)
    
    # Create agent_messages table
    op.create_table(
        'agent_messages',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('collaboration_id', sa.UUID(), nullable=False),
        sa.Column('step_id', sa.Text(), nullable=True),
        sa.Column('sender_agent_id', sa.UUID(), nullable=True),
        sa.Column('receiver_agent_id', sa.UUID(), nullable=True),
        sa.Column('message_type', sa.String(50), server_default='request', nullable=False),
        sa.Column('content_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('redaction_level', sa.String(50), server_default='none', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['collaboration_id'], ['collaboration_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_agent_id'], ['agent_instances.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['receiver_agent_id'], ['agent_instances.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "message_type IN ('request', 'response', 'notification', 'ack', 'tool_call', 'tool_result')",
            name='ck_agent_messages_message_type'
        ),
        sa.CheckConstraint(
            "redaction_level IN ('none', 'partial', 'full')",
            name='ck_agent_messages_redaction_level'
        )
    )
    
    # Create indexes for agent_messages
    with op.batch_alter_table('agent_messages', schema=None) as batch_op:
        batch_op.create_index('idx_messages_collab', ['collaboration_id', 'created_at'], unique=False)
        batch_op.create_index('idx_messages_step', ['step_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_messages_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_messages_sender_agent_id'), ['sender_agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_messages_receiver_agent_id'), ['receiver_agent_id'], unique=False)


def downgrade() -> None:
    """Drop agent_messages and collaboration_sessions tables."""
    # Drop agent_messages table (will drop indexes automatically)
    op.drop_table('agent_messages')
    
    # Drop collaboration_sessions table (will drop indexes automatically)
    op.drop_table('collaboration_sessions')
