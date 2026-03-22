"""add_agent_id_and_endpoint_group_id_to_agent_instances

Revision ID: b243438ff66f
Revises: 3ee3e8a37866
Create Date: 2026-03-22 20:54:39.852357

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b243438ff66f'
down_revision: Union[str, Sequence[str], None] = '3ee3e8a37866'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add agent_id, endpoint_group_id, phone_no, and whatsapp_key columns to agent_instances table.
    
    - agent_id: Unique identifier for agent instance (TEXT, UNIQUE, nullable for existing rows)
    - endpoint_group_id: Foreign key to llm_endpoint_groups (UUID, nullable)
    - phone_no: Phone number for agent instance (TEXT, nullable)
    - whatsapp_key: WhatsApp authentication key (TEXT, nullable)
    """
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agent_id', sa.Text(), nullable=True, comment='Unique identifier for agent instance'))
        batch_op.create_index(batch_op.f('ix_agent_instances_agent_id'), ['agent_id'], unique=True)
        
        batch_op.add_column(sa.Column('endpoint_group_id', sa.UUID(), nullable=True, comment='Reference to LLM endpoint group configuration'))
        batch_op.create_foreign_key(
            'fk_agent_instances_endpoint_group_id',
            'llm_endpoint_groups',
            ['endpoint_group_id'],
            ['id'],
            ondelete='SET NULL'
        )
        
        batch_op.add_column(sa.Column('phone_no', sa.Text(), nullable=True, comment='Agent phone number in free-form format'))
        
        batch_op.add_column(sa.Column('whatsapp_key', sa.Text(), nullable=True, comment='WhatsApp authentication key for agent'))


def downgrade() -> None:
    """Remove agent_id, endpoint_group_id, phone_no, and whatsapp_key columns from agent_instances table."""
    with op.batch_alter_table('agent_instances', schema=None) as batch_op:
        batch_op.drop_column('whatsapp_key')
        batch_op.drop_column('phone_no')
        batch_op.drop_constraint('fk_agent_instances_endpoint_group_id', type_='foreignkey')
        batch_op.drop_column('endpoint_group_id')
        batch_op.drop_index(batch_op.f('ix_agent_instances_agent_id'))
        batch_op.drop_column('agent_id')
