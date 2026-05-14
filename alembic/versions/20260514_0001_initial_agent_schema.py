"""initial agent schema

Revision ID: 20260514_0001
Revises:
Create Date: 2026-05-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260514_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_acc",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phoneno", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "llm_endpoint",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=1024), nullable=False),
        sa.Column("enc_key", sa.String(length=1024), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("max_token", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_acc.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_endpoint_user_id"), "llm_endpoint", ["user_id"], unique=False)

    op.create_table(
        "llm_group",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_acc.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_group_user_id"), "llm_group", ["user_id"], unique=False)

    op.create_table(
        "agent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("llm_group_id", sa.Integer(), nullable=False),
        sa.Column("agent_type", sa.String(length=100), nullable=False),
        sa.Column("is_sub_agent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("phone_no", sa.String(length=50), nullable=True),
        sa.Column("whatsapp_key", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["llm_group_id"], ["llm_group.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_acc.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_index(op.f("ix_agent_llm_group_id"), "agent", ["llm_group_id"], unique=False)
    op.create_index(op.f("ix_agent_user_id"), "agent", ["user_id"], unique=False)

    op.create_table(
        "llm_level",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("llm_group_id", sa.Integer(), nullable=False),
        sa.Column("llm_endpoint_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("seq_no", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["llm_endpoint_id"], ["llm_endpoint.id"]),
        sa.ForeignKeyConstraint(["llm_group_id"], ["llm_group.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_level_llm_endpoint_id"), "llm_level", ["llm_endpoint_id"], unique=False)
    op.create_index(op.f("ix_llm_level_llm_group_id"), "llm_level", ["llm_group_id"], unique=False)

    op.create_table(
        "long_term_mem",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("token", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_long_term_mem_agent_id"), "long_term_mem", ["agent_id"], unique=False)

    op.create_table(
        "memory_block",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("memory_type", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("last_upd_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memory_block_agent_id"), "memory_block", ["agent_id"], unique=False)

    op.create_table(
        "session",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recv_agent_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("session_type", sa.String(length=100), nullable=False),
        sa.Column("sender_agent_id", sa.Integer(), nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["recv_agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["sender_agent_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(op.f("ix_session_recv_agent_id"), "session", ["recv_agent_id"], unique=False)
    op.create_index(op.f("ix_session_sender_agent_id"), "session", ["sender_agent_id"], unique=False)

    op.create_table(
        "agent_msg_hist",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("msg_type", sa.String(length=100), nullable=False),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("token", sa.Integer(), nullable=True),
        sa.Column("is_summary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_analyst", sa.Integer(), nullable=True),
        sa.Column("meta_data", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_msg_hist_session_id"), "agent_msg_hist", ["session_id"], unique=False)

    op.create_table(
        "short_term_mem",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("token", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_short_term_mem_session_id"), "short_term_mem", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_short_term_mem_session_id"), table_name="short_term_mem")
    op.drop_table("short_term_mem")
    op.drop_index(op.f("ix_agent_msg_hist_session_id"), table_name="agent_msg_hist")
    op.drop_table("agent_msg_hist")
    op.drop_index(op.f("ix_session_sender_agent_id"), table_name="session")
    op.drop_index(op.f("ix_session_recv_agent_id"), table_name="session")
    op.drop_table("session")
    op.drop_index(op.f("ix_memory_block_agent_id"), table_name="memory_block")
    op.drop_table("memory_block")
    op.drop_index(op.f("ix_long_term_mem_agent_id"), table_name="long_term_mem")
    op.drop_table("long_term_mem")
    op.drop_index(op.f("ix_llm_level_llm_group_id"), table_name="llm_level")
    op.drop_index(op.f("ix_llm_level_llm_endpoint_id"), table_name="llm_level")
    op.drop_table("llm_level")
    op.drop_index(op.f("ix_agent_user_id"), table_name="agent")
    op.drop_index(op.f("ix_agent_llm_group_id"), table_name="agent")
    op.drop_table("agent")
    op.drop_index(op.f("ix_llm_group_user_id"), table_name="llm_group")
    op.drop_table("llm_group")
    op.drop_index(op.f("ix_llm_endpoint_user_id"), table_name="llm_endpoint")
    op.drop_table("llm_endpoint")
    op.drop_table("user_acc")
