"""add is_summarized and is_analyzed to agent_messages

Revision ID: m3n4o5p6q7r8
Revises: c43b015b6f42
Create Date: 2026-03-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, Sequence[str], None] = 'c43b015b6f42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_summarized and is_analyzed boolean fields to agent_messages table.

    These fields are used to track whether messages have been processed for
    long-term memory (LTM) summarization and analysis.
    """
    with op.batch_alter_table('agent_messages', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_summarized',
                sa.Boolean(),
                nullable=False,
                server_default='false',
                comment='Whether this message has been summarized for LTM'
            )
        )
        batch_op.add_column(
            sa.Column(
                'is_analyzed',
                sa.Boolean(),
                nullable=False,
                server_default='false',
                comment='Whether this message has been analyzed for LTM'
            )
        )
        # Add index for efficient querying of unsummarized messages
        batch_op.create_index(
            'idx_agent_messages_is_summarized',
            ['is_summarized', 'created_at'],
            unique=False
        )


def downgrade() -> None:
    """Remove is_summarized and is_analyzed fields from agent_messages table."""
    with op.batch_alter_table('agent_messages', schema=None) as batch_op:
        batch_op.drop_index('idx_agent_messages_is_summarized')
        batch_op.drop_column('is_analyzed')
        batch_op.drop_column('is_summarized')
