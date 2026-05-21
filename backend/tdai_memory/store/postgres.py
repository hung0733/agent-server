from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg

from ..models import L0Record, MemoryRecord, PipelineSessionState

logger = logging.getLogger(__name__)

L1_DB_COLUMNS = {
    "id",
    "agent_id",
    "content",
    "type",
    "priority",
    "scene_name",
    "timestamps",
    "created_at",
    "updated_at",
    "session_key",
    "session_id",
}


def _parse_iso(iso_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _jieba_tokenize(query: str) -> str:
    import jieba

    tokens = [t.strip() for t in jieba.cut_for_search(query) if t.strip()]
    if not tokens:
        return query
    return " & ".join(tokens)


class PostgresStore:
    def __init__(self, postgres_url: str, schema: str = "public") -> None:
        self._pool: asyncpg.Pool | None = None
        self._url = postgres_url
        self._schema = schema

    async def initialize(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._url,
            min_size=2,
            max_size=10,
            server_settings={"search_path": self._schema},
        )
        logger.info("PostgresStore initialized")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def upsert_l0(self, record: L0Record) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO l0_conversations (id, agent_id, session_key, session_id, role, message_text, recorded_at, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    agent_id = EXCLUDED.agent_id,
                    session_key = EXCLUDED.session_key,
                    session_id = EXCLUDED.session_id,
                    role = EXCLUDED.role,
                    message_text = EXCLUDED.message_text,
                    recorded_at = EXCLUDED.recorded_at,
                    timestamp = EXCLUDED.timestamp
                """,
                record.id,
                record.agent_id,
                record.session_key,
                record.session_id,
                record.role,
                record.message_text,
                _parse_iso(record.recorded_at),
                record.timestamp,
            )

    async def delete_l0(self, record_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM l0_conversations WHERE id = $1",
                record_id,
            )

    async def delete_l0_expired(self, cutoff_iso: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM l0_conversations WHERE recorded_at < $1",
                _parse_iso(cutoff_iso),
            )
            parts = result.split()
            return int(parts[-1]) if parts else 0

    async def count_l0(self, agent_id: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM l0_conversations WHERE agent_id = $1",
                agent_id,
            )
            return row[0]

    async def query_l0_for_l1(
        self,
        agent_id: str,
        session_key: str,
        after_timestamp_ms: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, agent_id, session_key, session_id, role, message_text, recorded_at, timestamp
                FROM l0_conversations
                WHERE agent_id = $1 AND session_key = $2 AND timestamp > $3
                ORDER BY timestamp
                LIMIT $4
                """,
                agent_id,
                session_key,
                after_timestamp_ms,
                limit,
            )
            return [dict(row) for row in rows]

    async def get_all_l0_texts(self, agent_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, message_text, recorded_at FROM l0_conversations WHERE agent_id = $1",
                agent_id,
            )
            return [dict(row) for row in rows]

    async def upsert_l1(self, record: MemoryRecord) -> None:
        data = {k: v for k, v in record.model_dump().items() if k in L1_DB_COLUMNS}
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO l1_records (id, agent_id, content, type, priority, scene_name, timestamps, created_at, updated_at, session_key, session_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (id) DO UPDATE SET
                    agent_id = EXCLUDED.agent_id,
                    content = EXCLUDED.content,
                    type = EXCLUDED.type,
                    priority = EXCLUDED.priority,
                    scene_name = EXCLUDED.scene_name,
                    timestamps = EXCLUDED.timestamps,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    session_key = EXCLUDED.session_key,
                    session_id = EXCLUDED.session_id
                """,
                data["id"],
                data["agent_id"],
                data["content"],
                data["type"],
                data["priority"],
                data["scene_name"],
                data["timestamps"],
                _parse_iso(data["created_at"]),
                _parse_iso(data["updated_at"]),
                data["session_key"],
                data["session_id"],
            )

    async def delete_l1(self, record_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM l1_records WHERE id = $1",
                record_id,
            )

    async def delete_l1_batch(self, record_ids: list[str]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM l1_records WHERE id = ANY($1)",
                record_ids,
            )

    async def delete_l1_expired(self, cutoff_iso: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM l1_records WHERE updated_at < $1",
                _parse_iso(cutoff_iso),
            )
            parts = result.split()
            return int(parts[-1]) if parts else 0

    async def count_l1(self, agent_id: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM l1_records WHERE agent_id = $1",
                agent_id,
            )
            return row[0]

    async def query_l1_records(
        self,
        agent_id: str,
        type_filter: str | None = None,
        scene_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            if type_filter and scene_filter:
                rows = await conn.fetch(
                    """
                    SELECT id, agent_id, content, type, priority, scene_name, timestamps, created_at, updated_at, session_key, session_id
                    FROM l1_records
                    WHERE agent_id = $1 AND type = $2 AND scene_name = $3
                    LIMIT $4
                    """,
                    agent_id,
                    type_filter,
                    scene_filter,
                    limit,
                )
            elif type_filter:
                rows = await conn.fetch(
                    """
                    SELECT id, agent_id, content, type, priority, scene_name, timestamps, created_at, updated_at, session_key, session_id
                    FROM l1_records
                    WHERE agent_id = $1 AND type = $2
                    LIMIT $3
                    """,
                    agent_id,
                    type_filter,
                    limit,
                )
            elif scene_filter:
                rows = await conn.fetch(
                    """
                    SELECT id, agent_id, content, type, priority, scene_name, timestamps, created_at, updated_at, session_key, session_id
                    FROM l1_records
                    WHERE agent_id = $1 AND scene_name = $2
                    LIMIT $3
                    """,
                    agent_id,
                    scene_filter,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, agent_id, content, type, priority, scene_name, timestamps, created_at, updated_at, session_key, session_id
                    FROM l1_records
                    WHERE agent_id = $1
                    LIMIT $2
                    """,
                    agent_id,
                    limit,
                )
            return [dict(row) for row in rows]

    async def get_all_l1_texts(self, agent_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, content, updated_at FROM l1_records WHERE agent_id = $1",
                agent_id,
            )
            return [dict(row) for row in rows]

    async def search_l0_fts(self, agent_id: str, query: str, limit: int = 10) -> list[dict]:
        tsquery = _jieba_tokenize(query)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, role, message_text, recorded_at,
                       ts_rank(to_tsvector('simple', message_text), to_tsquery('simple', $3)) AS score
                FROM l0_conversations
                WHERE agent_id = $1
                  AND to_tsvector('simple', message_text) @@ to_tsquery('simple', $3)
                ORDER BY score DESC
                LIMIT $2
                """,
                agent_id,
                limit,
                tsquery,
            )
            return [dict(row) for row in rows]

    async def search_l1_fts(self, agent_id: str, query: str, limit: int = 10) -> list[dict]:
        tsquery = _jieba_tokenize(query)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, content, type, priority, scene_name, timestamps,
                       ts_rank(to_tsvector('simple', content), to_tsquery('simple', $3)) AS score
                FROM l1_records
                WHERE agent_id = $1
                  AND to_tsvector('simple', content) @@ to_tsquery('simple', $3)
                ORDER BY score DESC
                LIMIT $2
                """,
                agent_id,
                limit,
                tsquery,
            )
            return [dict(row) for row in rows]

    async def read_pipeline_state(
        self, agent_id: str, session_key: str
    ) -> PipelineSessionState | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT agent_id, session_key, conversation_count,
                       last_extraction_time, last_extraction_updated_time,
                       last_active_time, l2_pending_l1_count, warmup_threshold,
                       l2_last_extraction_time
                FROM pipeline_state
                WHERE agent_id = $1 AND session_key = $2
                """,
                agent_id,
                session_key,
            )
            if row is None:
                return None
            return PipelineSessionState(**dict(row))

    async def write_pipeline_state(self, state: PipelineSessionState) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pipeline_state (
                    agent_id, session_key, conversation_count,
                    last_extraction_time, last_extraction_updated_time,
                    last_active_time, l2_pending_l1_count, warmup_threshold,
                    l2_last_extraction_time
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (agent_id, session_key) DO UPDATE SET
                    conversation_count = EXCLUDED.conversation_count,
                    last_extraction_time = EXCLUDED.last_extraction_time,
                    last_extraction_updated_time = EXCLUDED.last_extraction_updated_time,
                    last_active_time = EXCLUDED.last_active_time,
                    l2_pending_l1_count = EXCLUDED.l2_pending_l1_count,
                    warmup_threshold = EXCLUDED.warmup_threshold,
                    l2_last_extraction_time = EXCLUDED.l2_last_extraction_time
                """,
                state.agent_id,
                state.session_key,
                state.conversation_count,
                _parse_iso(state.last_extraction_time) if state.last_extraction_time else None,
                _parse_iso(state.last_extraction_updated_time) if state.last_extraction_updated_time else None,
                state.last_active_time,
                state.l2_pending_l1_count,
                state.warmup_threshold,
                _parse_iso(state.l2_last_extraction_time) if state.l2_last_extraction_time else None,
            )

    async def get_embedding_meta(self, agent_id: str, key: str) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM embedding_meta WHERE agent_id = $1 AND key = $2",
                agent_id,
                key,
            )
            return row["value"] if row else None

    async def set_embedding_meta(self, agent_id: str, key: str, value: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO embedding_meta (agent_id, key, value)
                VALUES ($1, $2, $3)
                ON CONFLICT (agent_id, key) DO UPDATE SET value = EXCLUDED.value
                """,
                agent_id,
                key,
                value,
            )
