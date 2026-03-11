"""add long term memory table and update message table

Revision ID: 004
Revises: 003
Create Date: 2026-03-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 創建 long_term_memory 表
    op.create_table(
        "long_term_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("vector_content", sa.Text(), nullable=True),  # pgvector vector(1024)
        sa.Column("importance", sa.Integer(), server_default="5"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="long_term_memory_pkey"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_long_term_memory_agent_id")
    )
    
    # 2. 在 message 表加入 long_term_mem_id 欄位
    op.add_column(
        "message",
        sa.Column("long_term_mem_id", sa.Integer(), nullable=True)
    )
    
    # 3. 建立外鍵約束
    op.create_foreign_key(
        "fk_message_long_term_mem_id",
        "message",
        "long_term_memory",
        ["long_term_mem_id"],
        ["id"],
        ondelete="SET NULL"
    )
    
    # 4. 建立 Index 優化「未鞏固訊息」的查詢
    op.create_index(
        "idx_message_not_summarized",
        "message",
        ["session_id"],
        postgresql_where=sa.text("long_term_mem_id IS NULL")
    )
    
    # 5. 建立 Vector Index (使用 HNSW)，提高搜尋速度
    # 注意：需要先安裝 pgvector extension，如果尚未安裝
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_index(
        "idx_ltm_vector",
        "long_term_memory",
        ["vector_content"],
        postgresql_using="hnsw",
        postgresql_with={"opclass": "vector_cosine_ops"}
    )


def downgrade() -> None:
    # 5. 刪除 Vector Index
    op.drop_index("idx_ltm_vector", table_name="long_term_memory")
    
    # 4. 刪除未鞏固訊息的 Index
    op.drop_index("idx_message_not_summarized", table_name="message")
    
    # 3. 刪除外鍵約束
    op.drop_constraint("fk_message_long_term_mem_id", "message", type_="foreignkey")
    
    # 2. 移除 message 表的 long_term_mem_id 欄位
    op.drop_column("message", "long_term_mem_id")
    
    # 1. 刪除 long_term_memory 表
    op.drop_table("long_term_memory")