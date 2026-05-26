"""ensure runner state round index

Revision ID: 20260526_0007
Revises: 20260522_0006
Create Date: 2026-05-26
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "20260526_0007"
down_revision: str | None = "20260522_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_SCHEMA = os.getenv("MEMORY_SCHEMA", "memories")


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_SCHEMA}.runner_states (
            agent_id TEXT NOT NULL,
            session_key TEXT NOT NULL,
            last_captured_timestamp BIGINT NOT NULL DEFAULT 0,
            last_l1_cursor TEXT,
            last_scene_name TEXT DEFAULT '',
            round_index INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (agent_id, session_key)
        )
    """)
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.runner_states
        ADD COLUMN IF NOT EXISTS round_index INTEGER NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.runner_states
        DROP COLUMN IF EXISTS round_index
    """)
