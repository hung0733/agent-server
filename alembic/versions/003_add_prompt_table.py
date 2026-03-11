"""add prompt table

Revision ID: 003
Revises: 002
Create Date: 2026-03-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 創建序列
    op.execute("CREATE SEQUENCE \"public\".prompt_id_seq INCREMENT 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1")
    
    # 創建表
    op.create_table(
        "prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("prompt_type", sa.String(length=50), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("retry_prompt", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="prompt_pkey"),
        sa.UniqueConstraint("code", name="uq_prompt_code")
    )


def downgrade() -> None:
    # 刪除表
    op.drop_table("prompt")
    
    # 刪除序列
    op.execute("DROP SEQUENCE \"public\".prompt_id_seq")