"""add soul memory table

Revision ID: 007
Revises: 006
Create Date: 2026-03-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 確保 vector extension 已開
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # 1. 創建 soul_memory 表
    op.create_table(
        "soul_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),  # 'soul', 'identity', 'user_profile'
        sa.Column("mem_key", sa.String(100), nullable=False),  # 用於 UPSERT 的唯一鍵
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),  # vector(1024) - BGE-M3 向量
        sa.Column("confidence", sa.Float(), default=0.1),
        sa.Column("hit_count", sa.Integer(), default=1),
        sa.Column("status", sa.String(20), default='staging'),  # 'staging', 'active', 'archived'
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("metadata", sa.JSON(), nullable=True),  # JSONB
        sa.PrimaryKeyConstraint("id", name="soul_memory_pkey")
    )
    
    # 2. 建立 IVFFlat Index 優化向量相似度搜索
    # 注意：IVFFlat index 需要在表創建後才能建立
    op.execute('CREATE INDEX IF NOT EXISTS idx_soul_memory_embedding ON soul_memory USING ivfflat (embedding vector_cosine_ops)')
    
    # 3. 建立 mem_key 的 unique index 用於 UPSERT
    op.create_index(
        "idx_soul_memory_mem_key",
        "soul_memory",
        ["mem_key"],
        unique=True
    )
    
    # 4. 建立 category index 用於分類查詢
    op.create_index(
        "idx_soul_memory_category",
        "soul_memory",
        ["category"]
    )


def downgrade() -> None:
    # 4. 刪除 category index
    op.drop_index("idx_soul_memory_category", table_name="soul_memory")
    
    # 3. 刪除 mem_key unique index
    op.drop_index("idx_soul_memory_mem_key", table_name="soul_memory")
    
    # 2. 刪除 IVFFlat index
    op.execute('DROP INDEX IF EXISTS idx_soul_memory_embedding')
    
    # 1. 刪除 soul_memory 表
    op.drop_table("soul_memory")
