"""remove agent_id from message table

Revision ID: 002
Revises: 001_initial_schema.py
Create Date: 2026-03-11 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 先刪除外鍵約束
    op.drop_constraint('message_agent_id_fkey', 'message', type_='foreignkey')
    
    # 再刪除欄位
    op.drop_column('message', 'agent_id')
    
    # 修改 create_date 為 TIMESTAMPTZ
    op.alter_column('message', 'create_date',
               existing_type=sa.TIMESTAMP(),
               type_=sa.TIMESTAMP(timezone=True),
               existing_nullable=False,
               postgresql_using='create_date AT TIME ZONE \'UTC\'')
    
    # 創建 session_id 索引
    op.create_index('idx_message_session_id', 'message', ['session_id'])


def downgrade() -> None:
    # 刪除索引
    op.drop_index('idx_message_session_id', table_name='message')
    
    # 恢復 create_date 為 TIMESTAMP (無時區)
    op.alter_column('message', 'create_date',
               existing_type=sa.TIMESTAMP(timezone=True),
               type_=sa.TIMESTAMP(),
               existing_nullable=False,
               postgresql_using='create_date AT TIME ZONE \'UTC\'')
    
    # 重新添加 agent_id 欄位 (需要外鍵約束)
    op.add_column('message', sa.Column('agent_id', sa.Integer(), nullable=True))
    
    # 重新創建外鍵約束
    op.create_foreign_key(
        'message_agent_id_fkey',
        'message', 'agent',
        ['agent_id'], ['id']
    )