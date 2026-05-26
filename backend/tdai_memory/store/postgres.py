from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import asyncpg

from backend.i18n import t
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
    "metadata_json",
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


def _to_iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _jieba_segment(text: str) -> str:
    import jieba

    tokens = [t.strip() for t in jieba.cut_for_search(text) if t.strip()]
    if not tokens:
        return text
    return " ".join(tokens)


def _jieba_tsquery(query: str) -> str:
    import jieba

    tokens = [t.strip() for t in jieba.cut_for_search(query) if t.strip()]
    if not tokens:
        return query
    return " | ".join(tokens)


class PostgresStore:
    supports_deferred_embedding = False

    def __init__(self, postgres_url: str, schema: str = "public") -> None:
        self._pool: asyncpg.Pool | None = None
        self._url = postgres_url
        self._schema = schema
        self._degraded = False

    async def initialize(self) -> None:
        try:
            temp_conn = await asyncpg.connect(self._url)
            try:
                await temp_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            finally:
                await temp_conn.close()

            self._pool = await asyncpg.create_pool(
                self._url,
                min_size=2,
                max_size=10,
                server_settings={"search_path": self._schema},
            )
        except Exception:
            logger.exception(t("tdai_memory.store.postgres_init_failed_degraded"))
            self._degraded = True
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS l0_conversations (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        session_key TEXT NOT NULL,
                        session_id TEXT DEFAULT '',
                        role TEXT NOT NULL,
                        message_text TEXT NOT NULL,
                        fts_text TEXT NOT NULL DEFAULT '',
                        recorded_at TIMESTAMPTZ NOT NULL,
                        timestamp BIGINT NOT NULL
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_l0_agent_session
                        ON l0_conversations(agent_id, session_key)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_l0_agent_recorded
                        ON l0_conversations(agent_id, recorded_at)
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS l1_records (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        type TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 0,
                        scene_name TEXT NOT NULL DEFAULT '',
                        timestamps TEXT[] NOT NULL DEFAULT '{}',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        fts_text TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        session_key TEXT NOT NULL DEFAULT '',
                        session_id TEXT NOT NULL DEFAULT ''
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_l1_agent_type
                        ON l1_records(agent_id, type)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_l1_agent_scene
                        ON l1_records(agent_id, scene_name)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_l1_agent_session
                        ON l1_records(agent_id, session_key)
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS pipeline_state (
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
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS embedding_meta (
                        agent_id TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        PRIMARY KEY (agent_id, key)
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS runner_states (
                        agent_id TEXT NOT NULL,
                        session_key TEXT NOT NULL,
                        last_captured_timestamp BIGINT NOT NULL DEFAULT 0,
                        last_l1_cursor TEXT,
                        last_scene_name TEXT DEFAULT '',
                        round_index INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (agent_id, session_key)
                    )
                """)
        except Exception:
            logger.exception(t("tdai_memory.store.postgres_schema_init_failed_degraded"))
            self._degraded = True
            return

        logger.info(t("tdai_memory.store.postgres_initialized"))

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    def is_degraded(self) -> bool:
        return self._degraded

    def _safe_acquire(self):
        if self._degraded or self._pool is None:
            return None
        return self._pool.acquire

    async def upsert_l0(self, record: L0Record) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO l0_conversations (id, agent_id, session_key, session_id, role, message_text, fts_text, recorded_at, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (id) DO UPDATE SET
                        agent_id = EXCLUDED.agent_id,
                        session_key = EXCLUDED.session_key,
                        session_id = EXCLUDED.session_id,
                        role = EXCLUDED.role,
                        message_text = EXCLUDED.message_text,
                        fts_text = EXCLUDED.fts_text,
                        recorded_at = EXCLUDED.recorded_at,
                        timestamp = EXCLUDED.timestamp
                    """,
                    record.id,
                    record.agent_id,
                    record.session_key,
                    record.session_id,
                    record.role,
                    record.message_text,
                    _jieba_segment(record.message_text),
                    _parse_iso(record.recorded_at),
                    record.timestamp,
                )
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.upsert_l0_failed"), record.id)
            return False

    async def delete_l0(self, record_id: str) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("DELETE FROM l0_conversations WHERE id = $1", record_id)
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.delete_l0_failed"), record_id)
            return False

    async def delete_l0_expired(self, cutoff_iso: str) -> int:
        if self._degraded or self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM l0_conversations WHERE recorded_at < $1",
                    _parse_iso(cutoff_iso),
                )
                parts = result.split()
                return int(parts[-1]) if parts else 0
        except Exception:
            logger.exception(t("tdai_memory.store.delete_l0_expired_failed"))
            return 0

    async def count_l0(self, agent_id: str) -> int:
        if self._degraded or self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) FROM l0_conversations WHERE agent_id = $1", agent_id
                )
                return row[0]
        except Exception:
            logger.exception(t("tdai_memory.store.count_l0_failed"))
            return 0

    async def query_l0_for_l1(
        self,
        agent_id: str,
        session_key: str,
        after_recorded_at_epoch_ms: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        after_iso = datetime.fromtimestamp(after_recorded_at_epoch_ms / 1000.0, tz=timezone.utc).isoformat()
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, agent_id, session_key, session_id, role, message_text, recorded_at, timestamp
                    FROM l0_conversations
                    WHERE agent_id = $1 AND session_key = $2 AND recorded_at > $3
                    ORDER BY recorded_at
                    LIMIT $4
                    """,
                    agent_id,
                    session_key,
                    _parse_iso(after_iso),
                    limit,
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.query_l0_for_l1_failed"))
            return []

    async def get_all_l0_texts(self, agent_id: str) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, message_text, recorded_at FROM l0_conversations WHERE agent_id = $1", agent_id
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.get_all_l0_texts_failed"))
            return []

    async def upsert_l1(self, record: MemoryRecord) -> bool:
        if self._degraded or self._pool is None:
            return False
        data = {k: v for k, v in record.model_dump().items() if k in L1_DB_COLUMNS}
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO l1_records (id, agent_id, content, type, priority, scene_name, timestamps, metadata_json, fts_text, created_at, updated_at, session_key, session_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (id) DO UPDATE SET
                        agent_id = EXCLUDED.agent_id,
                        content = EXCLUDED.content,
                        type = EXCLUDED.type,
                        priority = EXCLUDED.priority,
                        scene_name = EXCLUDED.scene_name,
                        timestamps = EXCLUDED.timestamps,
                        metadata_json = EXCLUDED.metadata_json,
                        fts_text = EXCLUDED.fts_text,
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
                    data.get("metadata_json", "{}") if isinstance(data.get("metadata_json"), str) else json.dumps(data.get("metadata", data.get("metadata_json", {})), ensure_ascii=False),
                    _jieba_segment(data["content"]),
                    _parse_iso(data["created_at"]),
                    _parse_iso(data["updated_at"]),
                    data["session_key"],
                    data["session_id"],
                )
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.upsert_l1_failed"), record.id)
            return False

    async def delete_l1(self, record_id: str) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("DELETE FROM l1_records WHERE id = $1", record_id)
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.delete_l1_failed"), record_id)
            return False

    async def delete_l1_batch(self, record_ids: list[str]) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("DELETE FROM l1_records WHERE id = ANY($1)", record_ids)
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.delete_l1_batch_failed"))
            return False

    async def delete_l1_expired(self, cutoff_iso: str) -> int:
        if self._degraded or self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM l1_records WHERE updated_at < $1",
                    _parse_iso(cutoff_iso),
                )
                parts = result.split()
                return int(parts[-1]) if parts else 0
        except Exception:
            logger.exception(t("tdai_memory.store.delete_l1_expired_failed"))
            return 0

    async def count_l1(self, agent_id: str) -> int:
        if self._degraded or self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) FROM l1_records WHERE agent_id = $1", agent_id
                )
                return row[0]
        except Exception:
            logger.exception(t("tdai_memory.store.count_l1_failed"))
            return 0

    async def query_l1_records(
        self,
        agent_id: str,
        type_filter: str | None = None,
        scene_filter: str | None = None,
        session_key: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                if type_filter and scene_filter:
                    rows = await conn.fetch(
                        """
                        SELECT id, agent_id, content, type, priority, scene_name, timestamps, metadata_json, created_at, updated_at, session_key, session_id
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
                        SELECT id, agent_id, content, type, priority, scene_name, timestamps, metadata_json, created_at, updated_at, session_key, session_id
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
                        SELECT id, agent_id, content, type, priority, scene_name, timestamps, metadata_json, created_at, updated_at, session_key, session_id
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
                        SELECT id, agent_id, content, type, priority, scene_name, timestamps, metadata_json, created_at, updated_at, session_key, session_id
                        FROM l1_records
                        WHERE agent_id = $1
                        LIMIT $2
                        """,
                        agent_id,
                        limit,
                    )
            return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.query_l1_records_failed"))
            return []

    async def get_all_l1_texts(self, agent_id: str) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, content, updated_at FROM l1_records WHERE agent_id = $1", agent_id
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.get_all_l1_texts_failed"))
            return []

    async def search_l0_fts(self, agent_id: str, query: str, limit: int = 10) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        tsquery = _jieba_tsquery(query)
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, role, message_text, recorded_at,
                           ts_rank(to_tsvector('simple', fts_text), to_tsquery('simple', $3)) AS score
                    FROM l0_conversations
                    WHERE agent_id = $1
                      AND to_tsvector('simple', fts_text) @@ to_tsquery('simple', $3)
                    ORDER BY score DESC
                    LIMIT $2
                    """,
                    agent_id,
                    limit,
                    tsquery,
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.search_l0_fts_failed"))
            return []

    async def search_l1_fts(self, agent_id: str, query: str, limit: int = 10) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        tsquery = _jieba_tsquery(query)
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, content, type, priority, scene_name, timestamps,
                           ts_rank(to_tsvector('simple', fts_text), to_tsquery('simple', $3)) AS score
                    FROM l1_records
                    WHERE agent_id = $1
                      AND to_tsvector('simple', fts_text) @@ to_tsquery('simple', $3)
                    ORDER BY score DESC
                    LIMIT $2
                    """,
                    agent_id,
                    limit,
                    tsquery,
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.search_l1_fts_failed"))
            return []

    async def read_pipeline_state(
        self, agent_id: str, session_key: str
    ) -> PipelineSessionState | None:
        if self._degraded or self._pool is None:
            return None
        try:
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
                data = dict(row)
                data["last_extraction_time"] = _to_iso(data.get("last_extraction_time"))
                data["last_extraction_updated_time"] = _to_iso(
                    data.get("last_extraction_updated_time")
                )
                data["l2_last_extraction_time"] = _to_iso(
                    data.get("l2_last_extraction_time")
                )
                return PipelineSessionState(**data)
        except Exception:
            logger.exception(t("tdai_memory.store.read_pipeline_state_failed"))
            return None

    async def write_pipeline_state(self, state: PipelineSessionState) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
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
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.write_pipeline_state_failed"))
            return False

    async def read_runner_state(
        self, agent_id: str, session_key: str
    ) -> dict | None:
        if self._degraded or self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT agent_id, session_key, last_captured_timestamp,
                           last_l1_cursor, last_scene_name, round_index
                    FROM runner_states
                    WHERE agent_id = $1 AND session_key = $2
                    """,
                    agent_id,
                    session_key,
                )
                if row is None:
                    return None
                return dict(row)
        except Exception:
            logger.exception(t("tdai_memory.store.read_runner_state_failed"))
            return None

    async def write_runner_state(
        self,
        agent_id: str,
        session_key: str,
        last_captured_timestamp: int,
        last_l1_cursor: str | None = None,
        last_scene_name: str = "",
        round_index: int = 0,
    ) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO runner_states (agent_id, session_key, last_captured_timestamp, last_l1_cursor, last_scene_name, round_index)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (agent_id, session_key) DO UPDATE SET
                        last_captured_timestamp = EXCLUDED.last_captured_timestamp,
                        last_l1_cursor = EXCLUDED.last_l1_cursor,
                        last_scene_name = EXCLUDED.last_scene_name,
                        round_index = EXCLUDED.round_index
                    """,
                    agent_id,
                    session_key,
                    last_captured_timestamp,
                    last_l1_cursor,
                    last_scene_name,
                    round_index,
                )
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.write_runner_state_failed"))
            return False

    async def get_embedding_meta(self, agent_id: str, key: str) -> str | None:
        if self._degraded or self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM embedding_meta WHERE agent_id = $1 AND key = $2",
                    agent_id,
                    key,
                )
                return row["value"] if row else None
        except Exception:
            logger.exception(t("tdai_memory.store.get_embedding_meta_failed"))
            return None

    async def set_embedding_meta(self, agent_id: str, key: str, value: str) -> bool:
        if self._degraded or self._pool is None:
            return False
        try:
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
            return True
        except Exception:
            logger.exception(t("tdai_memory.store.set_embedding_meta_failed"))
            return False

    def get_capabilities(self) -> dict:
        return {
            "vector_search": False,
            "fts_search": not self._degraded,
            "native_hybrid_search": False,
            "sparse_vectors": False,
        }

    @property
    def supports_deferred_embedding(self) -> bool:
        return False

    def is_fts_available(self) -> bool:
        return not self._degraded and self._pool is not None

    async def update_l0_embedding(self, record_id: str, embedding: list[float]) -> bool:
        return True

    async def query_l0_grouped_by_session_id(
        self, agent_id: str, limit: int = 100
    ) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT session_key, array_agg(id ORDER BY recorded_at) AS record_ids,
                           count(*) AS message_count,
                           min(recorded_at) AS first_at,
                           max(recorded_at) AS last_at
                    FROM l0_conversations
                    WHERE agent_id = $1
                    GROUP BY session_key
                    ORDER BY last_at DESC
                    LIMIT $2
                    """,
                    agent_id,
                    limit,
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception(t("tdai_memory.store.query_l0_grouped_by_session_id_failed"))
            return []

    async def reindex_all(self, embed_fn, qdrant_store=None, on_progress=None) -> dict:
        l0_count = 0
        l1_count = 0
        all_l1_texts = await self._get_all_l1_texts_all_agents()
        if on_progress:
            on_progress("L1", 0)
        for row in all_l1_texts:
            try:
                embedding = await embed_fn(row["content"])
            except Exception:
                continue
            if qdrant_store is not None:
                try:
                    record = MemoryRecord(
                        id=row["id"],
                        agent_id=row["agent_id"],
                        content=row["content"],
                        type=row["type"],
                        priority=row["priority"],
                        scene_name=row["scene_name"],
                        timestamps=row["timestamps"],
                        metadata=json.loads(row["metadata_json"]) if row.get("metadata_json") else {},
                        created_at=str(row["created_at"]),
                        updated_at=str(row["updated_at"]),
                        session_key=row.get("session_key", ""),
                        session_id=row.get("session_id", ""),
                    )
                    await qdrant_store.upsert_l1(record, embedding)
                except Exception:
                    continue
            l1_count += 1
            if on_progress:
                on_progress("L1", l1_count)
        if on_progress:
            on_progress("L0", 0)
        l0_texts = await self._get_all_l0_texts_all_agents()
        for row in l0_texts:
            try:
                embedding = await embed_fn(row["message_text"])
            except Exception:
                continue
            if qdrant_store is not None:
                try:
                    record = L0Record(
                        id=row["id"],
                        agent_id=row["agent_id"],
                        session_key=row["session_key"],
                        session_id=row.get("session_id", ""),
                        role=row["role"],
                        message_text=row["message_text"],
                        recorded_at=str(row["recorded_at"]),
                        timestamp=row["timestamp"],
                    )
                    await qdrant_store.upsert_l0(record, embedding)
                except Exception:
                    continue
            l0_count += 1
            if on_progress:
                on_progress("L0", l0_count)
        return {"l0_count": l0_count, "l1_count": l1_count}

    async def _get_all_l0_texts_all_agents(self) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, agent_id, session_key, session_id, role, message_text, recorded_at, timestamp FROM l0_conversations"
                )
                return [dict(row) for row in rows]
        except Exception:
            return []

    async def _get_all_l1_texts_all_agents(self) -> list[dict]:
        if self._degraded or self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, agent_id, content, type, priority, scene_name, timestamps, metadata_json, created_at, updated_at, session_key, session_id FROM l1_records"
                )
                return [dict(row) for row in rows]
        except Exception:
            return []
