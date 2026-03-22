"""add_index_on_agent_instances_endpoint_group_id

Revision ID: c43b015b6f42
Revises: 93c9d5db432c
Create Date: 2026-03-22 21:31:08.438158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c43b015b6f42'
down_revision: Union[str, Sequence[str], None] = '93c9d5db432c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add index on agent_instances.endpoint_group_id for efficient FK lookups.
    
    This index was missing from the original migration b243438ff66f that added
    the endpoint_group_id foreign key column. Indexing FK columns is essential
    for efficient JOIN operations and foreign key constraint checks.
    """
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.create_index('idx_agent_instances_endpoint_group_id', ['endpoint_group_id'], unique=False)


def downgrade() -> None:
    """Remove index on agent_instances.endpoint_group_id."""
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.drop_index('idx_agent_instances_endpoint_group_id')
