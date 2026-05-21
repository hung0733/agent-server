"""add memory schema tables (l0_conversations, l1_records, pipeline_state, embedding_meta)

Revision ID: 20260521_0004
Revises: 20260518_0003
Create Date: 2026-05-21
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "20260521_0004"
down_revision: str | None = "20260518_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_SCHEMA = os.getenv("MEMORY_SCHEMA", "memories")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {MEMORY_SCHEMA}")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_SCHEMA}.l0_conversations (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            session_key TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            role TEXT NOT NULL,
            message_text TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            timestamp BIGINT NOT NULL
        )
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_l0_agent_session
            ON {MEMORY_SCHEMA}.l0_conversations(agent_id, session_key)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_l0_agent_recorded
            ON {MEMORY_SCHEMA}.l0_conversations(agent_id, recorded_at)
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_SCHEMA}.l1_records (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            content TEXT NOT NULL,
            type TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            scene_name TEXT NOT NULL DEFAULT '',
            timestamps TEXT[] NOT NULL DEFAULT '{{}}',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            session_key TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_l1_agent_type
            ON {MEMORY_SCHEMA}.l1_records(agent_id, type)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_l1_agent_scene
            ON {MEMORY_SCHEMA}.l1_records(agent_id, scene_name)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_l1_agent_session
            ON {MEMORY_SCHEMA}.l1_records(agent_id, session_key)
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_SCHEMA}.pipeline_state (
            agent_id TEXT NOT NULL,
            session_key TEXT NOT NULL,
            conversation_count INTEGER NOT NULL DEFAULT 0,
            last_extraction_time TIMESTAMPTZ,
            last_extraction_updated_time TIMESTAMPTZ,
            last_active_time BIGINT NOT NULL DEFAULT 0,
            l2_pending_l1_count INTEGER NOT NULL DEFAULT 0,
            warmup_threshold INTEGER NOT NULL DEFAULT 1,
            l2_last_extraction_time TIMESTAMPTZ,
            PRIMARY KEY (agent_id, session_key)
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_SCHEMA}.embedding_meta (
            agent_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (agent_id, key)
        )
    """)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {MEMORY_SCHEMA}.embedding_meta")
    op.execute(f"DROP TABLE IF EXISTS {MEMORY_SCHEMA}.pipeline_state")
    op.execute(f"DROP TABLE IF EXISTS {MEMORY_SCHEMA}.l1_records")
    op.execute(f"DROP TABLE IF EXISTS {MEMORY_SCHEMA}.l0_conversations")
