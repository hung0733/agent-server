"""update message table for summary and analysis flags

Revision ID: 005
Revises: 004
Create Date: 2026-03-12 00:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop Foreign Key Constraint
    op.drop_constraint("fk_message_long_term_mem_id", "message", type_="foreignkey")

    # 2. Drop Index
    op.drop_index("idx_message_not_summarized", table_name="message")
    
    # 3. Drop the column
    op.drop_column("message", "long_term_mem_id")

    # 4. Add new column: is_summaryed
    op.add_column("message", sa.Column("is_summaryed", sa.Boolean, server_default="false"))

    # 5. Add new column: is_analysed
    op.add_column("message", sa.Column("is_analysed", sa.Boolean, server_default="false"))

    # 6. Create indexes for efficient querying
    # Index for summary status - only for records where is_summaryed = FALSE
    op.execute("""
        CREATE INDEX idx_message_summary_status 
        ON message (is_summaryed) 
        WHERE is_summaryed = FALSE
    """)
    
    # Index for analysis status - only for records where is_analysed = FALSE
    op.execute("""
        CREATE INDEX idx_message_analyse_status 
        ON message (is_analysed) 
        WHERE is_analysed = FALSE
    """)


def downgrade() -> None:
    # 6. Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_message_analyse_status")
    op.execute("DROP INDEX IF EXISTS idx_message_summary_status")
    
    # 5. Remove new columns
    op.drop_column("message", "is_analysed")
    op.drop_column("message", "is_summaryed")

    # 4. Add back the long_term_mem_id column
    op.add_column("message", sa.Column("long_term_mem_id", sa.Integer(), nullable=True))

    # 3. Recreate index for not summarized messages
    op.execute("""
        CREATE INDEX idx_message_not_summarized 
        ON message (session_id) 
        WHERE long_term_mem_id IS NULL
    """)

    # 2. Recreate foreign key constraint
    op.create_foreign_key(
        "fk_message_long_term_mem_id",
        "message",
        "long_term_memory",
        ["long_term_mem_id"],
        ["id"],
        ondelete="SET NULL"
    )