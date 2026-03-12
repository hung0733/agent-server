"""add memory block table and agent is_inited column

Revision ID: 006
Revises: 005
Create Date: 2026-03-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 確保 vector extension 已開
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # 1. 創建 memory_block 表
    op.create_table(
        "memory_block",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(20), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("vector_content", Vector(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="memory_block_pkey"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_memory_block_agent_id")
    )
    
    # 2. 建立 Index 優化查詢
    op.create_index(
        "idx_memory_block_lookup",
        "memory_block",
        ["agent_id", "block_type"]
    )
    
    # 3. 在 agent 表加入 is_inited 欄位
    op.add_column(
        "agent",
        sa.Column("is_inited", sa.Boolean(), server_default="false")
    )


def downgrade() -> None:
    # 3. 移除 agent 表的 is_inited 欄位
    op.drop_column("agent", "is_inited")
    
    # 2. 刪除 Index
    op.drop_index("idx_memory_block_lookup", table_name="memory_block")
    
    # 1. 刪除 memory_block 表
    op.drop_table("memory_block")
