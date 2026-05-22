"""add memory fts columns

Revision ID: 20260522_0006
Revises: 20260521_0005
Create Date: 2026-05-22
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "20260522_0006"
down_revision: str | None = "20260521_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_SCHEMA = os.getenv("MEMORY_SCHEMA", "memories")


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.l0_conversations
        ADD COLUMN IF NOT EXISTS fts_text TEXT NOT NULL DEFAULT ''
    """)
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.l1_records
        ADD COLUMN IF NOT EXISTS metadata_json TEXT NOT NULL DEFAULT '{{}}'
    """)
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.l1_records
        ADD COLUMN IF NOT EXISTS fts_text TEXT NOT NULL DEFAULT ''
    """)
    op.execute(f"""
        UPDATE {MEMORY_SCHEMA}.l0_conversations
        SET fts_text = message_text
        WHERE fts_text = ''
    """)
    op.execute(f"""
        UPDATE {MEMORY_SCHEMA}.l1_records
        SET fts_text = content
        WHERE fts_text = ''
    """)


def downgrade() -> None:
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.l1_records
        DROP COLUMN IF EXISTS fts_text
    """)
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.l1_records
        DROP COLUMN IF EXISTS metadata_json
    """)
    op.execute(f"""
        ALTER TABLE IF EXISTS {MEMORY_SCHEMA}.l0_conversations
        DROP COLUMN IF EXISTS fts_text
    """)
