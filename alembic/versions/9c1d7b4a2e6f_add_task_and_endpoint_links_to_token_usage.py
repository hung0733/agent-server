"""add task and endpoint links to token_usage

Revision ID: 9c1d7b4a2e6f
Revises: 8301949ee373
Create Date: 2026-03-29 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9c1d7b4a2e6f"
down_revision: Union[str, Sequence[str], None] = "8301949ee373"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("token_usage", sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "token_usage",
        sa.Column("llm_endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_token_usage_task_id",
        "token_usage",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_token_usage_llm_endpoint_id",
        "token_usage",
        "llm_endpoints",
        ["llm_endpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_token_usage_task", "token_usage", ["task_id"], unique=False)
    op.create_index(
        "idx_token_usage_llm_endpoint",
        "token_usage",
        ["llm_endpoint_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_token_usage_llm_endpoint", table_name="token_usage")
    op.drop_index("idx_token_usage_task", table_name="token_usage")
    op.drop_constraint("fk_token_usage_llm_endpoint_id", "token_usage", type_="foreignkey")
    op.drop_constraint("fk_token_usage_task_id", "token_usage", type_="foreignkey")
    op.drop_column("token_usage", "llm_endpoint_id")
    op.drop_column("token_usage", "task_id")
