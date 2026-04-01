"""add sender_agent_id to collaboration_sessions

Revision ID: 07ef83296bf6
Revises: 92f88b46f5a0
Create Date: 2026-04-02 03:03:55.075428

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07ef83296bf6'
down_revision: Union[str, Sequence[str], None] = '92f88b46f5a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('collaboration_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'sender_agent_id',
            sa.UUID(),
            nullable=True,
            comment='Initiating agent in an agent-to-agent session',
        ))
        batch_op.alter_column('user_id', existing_type=sa.UUID(), nullable=True)
        batch_op.create_index(
            batch_op.f('ix_collaboration_sessions_sender_agent_id'),
            ['sender_agent_id'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_collaboration_sessions_sender_agent_id',
            'agent_instances',
            ['sender_agent_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('collaboration_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_collaboration_sessions_sender_agent_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_collaboration_sessions_sender_agent_id'))
        batch_op.alter_column('user_id', existing_type=sa.UUID(), nullable=False)
        batch_op.drop_column('sender_agent_id')
