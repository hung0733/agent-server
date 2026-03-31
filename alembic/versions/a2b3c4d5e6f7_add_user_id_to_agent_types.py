"""add_user_id_to_agent_types

Revision ID: a2b3c4d5e6f7
Revises: 9c1d7b4a2e6f
Create Date: 2026-03-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = '9c1d7b4a2e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agent_types', schema=None) as batch_op:
        # Drop old unique index and constraint on name alone
        batch_op.drop_index(batch_op.f('ix_agent_types_name'))
        batch_op.drop_constraint('uq_agent_types_name', type_='unique')

        # Add user_id column (nullable first so existing rows don't fail)
        batch_op.add_column(
            sa.Column('user_id', sa.UUID(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_agent_types_user_id',
            'users',
            ['user_id'],
            ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index('idx_agent_types_user_id', ['user_id'], unique=False)

        # Composite unique: one name per user
        batch_op.create_unique_constraint(
            'uq_agent_types_user_id_name', ['user_id', 'name']
        )

    # Guard: if orphaned rows exist, a user must exist to assign them to
    result = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM agent_types WHERE user_id IS NULL")
    )
    orphan_count = result.scalar()
    if orphan_count > 0:
        user_result = op.get_bind().execute(
            sa.text("SELECT COUNT(*) FROM users")
        )
        if user_result.scalar() == 0:
            raise RuntimeError(
                f"Cannot migrate: {orphan_count} agent_types row(s) have no user_id "
                "and no users exist to assign them to. Create a user first."
            )

    # Assign any existing agent_types rows to the first available user.
    # In a fresh multi-tenant deployment there should be no orphaned rows,
    # but a single-tenant seed install may have pre-existing data.
    op.execute("""
        UPDATE agent_types
        SET user_id = (SELECT id FROM users ORDER BY created_at LIMIT 1)
        WHERE user_id IS NULL
    """)

    # Make user_id NOT NULL after all rows have been assigned
    op.execute(
        "ALTER TABLE agent_types ALTER COLUMN user_id SET NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table('agent_types', schema=None) as batch_op:
        batch_op.drop_constraint('uq_agent_types_user_id_name', type_='unique')
        batch_op.drop_index('idx_agent_types_user_id')
        batch_op.drop_constraint('fk_agent_types_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
        batch_op.create_unique_constraint('uq_agent_types_name', ['name'])
        batch_op.create_index(batch_op.f('ix_agent_types_name'), ['name'], unique=True)
