# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportMissingParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportDeprecated=false
"""
PostgreSQL implementation of SessionStorage using asyncpg.

Provides unified schema with tenant_id for multitenancy.
Uses the centralized database pool from tools.db_pool.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Optional, Type, cast
from uuid import uuid4

import asyncpg

from utils.db_pool import configure_pool, get_pool
from .base import SessionStorage
from simplemem_cross_lite.types import (
    CrossObservation,
    EventKind,
    ObservationType,
    RedactionLevel,
    SessionEvent,
    SessionRecord,
    SessionStatus,
    SessionSummary,
)

logger = logging.getLogger(__name__)


class PostgresSessionStorage(SessionStorage):
    """
    PostgreSQL implementation of SessionStorage using asyncpg.

    Manages session lifecycle, events, observations, and summaries with
    tenant isolation. Uses the centralized global database pool.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        min_connections: int = 5,
        max_connections: int = 20,
    ) -> None:
        """
        Initialize PostgreSQL storage.

        Args:
            dsn: PostgreSQL connection string. If provided, configures the global
                 pool with this DSN (primarily for testing). If None, uses the
                 existing global pool (configured via environment variables).
            min_connections: Minimum pool connections (used when DSN provided)
            max_connections: Maximum pool connections (used when DSN provided)
        """
        self._dsn = dsn
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database schema. Must be called before use.

        If a DSN was provided in __init__, configures the global pool with it.
        Then runs schema migrations.
        """
        if self._dsn is not None:
            await configure_pool(dsn=self._dsn)
        
        pool = await get_pool()
        async with pool.acquire() as conn:
            await self._run_migrations(conn)
        self._initialized = True

    async def close(self) -> None:
        """Mark storage as closed. Does NOT close the global pool.

        The global pool is shared across the application and should only
        be closed at application shutdown, not per-storage instance.
        """
        self._initialized = False

    async def __aenter__(self) -> "PostgresSessionStorage":
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def _run_migrations(self, conn: asyncpg.Connection) -> None:
        """Create database schema if not exists."""
        schema_statements = [
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                content_session_id TEXT UNIQUE NOT NULL,
                memory_session_id TEXT UNIQUE NOT NULL,
                project TEXT NOT NULL,
                user_prompt TEXT,
                started_at TIMESTAMPTZ NOT NULL,
                ended_at TIMESTAMPTZ,
                status TEXT CHECK(status IN ('active', 'completed', 'failed')) DEFAULT 'active',
                metadata_json JSONB
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS session_events (
                event_id SERIAL PRIMARY KEY,
                memory_session_id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                kind TEXT CHECK(kind IN ('message', 'tool_use', 'file_change', 'note', 'system')) NOT NULL,
                title TEXT,
                payload_json JSONB,
                redaction_level TEXT DEFAULT 'none',
                FOREIGN KEY(memory_session_id) REFERENCES sessions(memory_session_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS observations (
                obs_id SERIAL PRIMARY KEY,
                memory_session_id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                type TEXT CHECK(type IN ('decision', 'bugfix', 'feature', 'refactor', 'discovery', 'change')) NOT NULL,
                title TEXT NOT NULL,
                subtitle TEXT,
                facts_json JSONB,
                narrative TEXT,
                concepts_json JSONB,
                files_json JSONB,
                vector_ref TEXT,
                FOREIGN KEY(memory_session_id) REFERENCES sessions(memory_session_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS session_summaries (
                summary_id SERIAL PRIMARY KEY,
                memory_session_id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                request TEXT,
                investigated TEXT,
                learned TEXT,
                completed TEXT,
                next_steps TEXT,
                vector_ref TEXT,
                FOREIGN KEY(memory_session_id) REFERENCES sessions(memory_session_id) ON DELETE CASCADE
            )
            """,
        ]
        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_content_id ON sessions(content_session_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_memory_id ON sessions(memory_session_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)",
            "CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(memory_session_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_kind ON session_events(kind)",
            "CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(memory_session_id)",
            "CREATE INDEX IF NOT EXISTS idx_observations_type ON observations(type)",
            "CREATE INDEX IF NOT EXISTS idx_summaries_session ON session_summaries(memory_session_id)",
        ]
        try:
            for statement in schema_statements:
                await conn.execute(statement)
            for statement in index_statements:
                await conn.execute(statement)
            logger.info("PostgreSQL schema migrations completed successfully")
        except Exception:
            logger.exception("Failed to run PostgreSQL migrations")
            raise

    async def create_session(
        self,
        tenant_id: str,
        content_session_id: str,
        project: str,
        user_prompt: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> SessionRecord:
        """Create a new session record."""
        memory_session_id = str(uuid4())
        started_at = self._now_datetime()
        metadata_json = json.dumps(metadata) if metadata is not None else None

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO sessions (
                        tenant_id, content_session_id, memory_session_id, project,
                        user_prompt, started_at, status, metadata_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (content_session_id) DO NOTHING
                    """,
                    tenant_id,
                    content_session_id,
                    memory_session_id,
                    project,
                    user_prompt,
                    started_at,
                    "active",
                    metadata_json,
                )
            except Exception:
                logger.exception("Failed to create session")
                raise

        session = await self.get_session_by_content_id(content_session_id)
        if session is None:
            raise RuntimeError("Failed to retrieve session after insert")
        return session

    async def get_session_by_content_id(
        self, content_session_id: str
    ) -> Optional[SessionRecord]:
        """Retrieve session by content session ID."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM sessions WHERE content_session_id = $1",
                    content_session_id,
                )
                return self._row_to_session(row) if row else None
            except Exception:
                logger.exception("Failed to fetch session by content_id")
                raise

    async def get_session_by_memory_id(
        self, memory_session_id: str
    ) -> Optional[SessionRecord]:
        """Retrieve session by memory session ID."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM sessions WHERE memory_session_id = $1",
                    memory_session_id,
                )
                return self._row_to_session(row) if row else None
            except Exception:
                logger.exception("Failed to fetch session by memory_id")
                raise

    async def get_session_by_id(self, session_id: int) -> Optional[SessionRecord]:
        """Retrieve session by database ID."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM sessions WHERE id = $1",
                    session_id,
                )
                return self._row_to_session(row) if row else None
            except Exception:
                logger.exception("Failed to fetch session by id")
                raise

    async def update_session_status(
        self,
        memory_session_id: str,
        status: SessionStatus,
        ended_at: Optional[str] = None,
    ) -> None:
        """Update session status and optionally set end time."""
        status_value = self._enum_to_value(status)
        ended_at_dt: Optional[datetime] = None

        if ended_at is not None:
            ended_at_dt = datetime.fromisoformat(ended_at)
        elif status_value in {"completed", "failed"}:
            ended_at_dt = self._now_datetime()

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    UPDATE sessions
                    SET status = $1, ended_at = $2
                    WHERE memory_session_id = $3
                    """,
                    status_value,
                    ended_at_dt,
                    memory_session_id,
                )
            except Exception:
                logger.exception("Failed to update session status")
                raise

    async def list_sessions(
        self,
        tenant_id: Optional[str] = None,
        project: Optional[str] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionRecord]:
        """List sessions with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if tenant_id:
            conditions.append(f"tenant_id = ${param_idx}")
            params.append(tenant_id)
            param_idx += 1
        if project:
            conditions.append(f"project = ${param_idx}")
            params.append(project)
            param_idx += 1
        if status:
            status_value = self._enum_to_value(status)
            conditions.append(f"status = ${param_idx}")
            params.append(status_value)
            param_idx += 1

        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            f"SELECT * FROM sessions {where_sql} "
            f"ORDER BY started_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        )
        params.extend([limit, offset])

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(query, *params)
                return [self._row_to_session(row) for row in rows]
            except Exception:
                logger.exception("Failed to list sessions")
                raise

    async def add_event(
        self,
        memory_session_id: str,
        kind: EventKind,
        title: Optional[str] = None,
        payload_json: Optional[dict[str, object]] = None,
        redaction_level: Optional[RedactionLevel] = None,
    ) -> int:
        """Add an event to a session."""
        timestamp = self._now_datetime()
        kind_value = self._enum_to_value(kind)
        redaction_value = self._enum_to_value(redaction_level, default="none")

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO session_events (
                        memory_session_id, timestamp, kind, title, payload_json, redaction_level
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING event_id
                    """,
                    memory_session_id,
                    timestamp,
                    kind_value,
                    title,
                    payload_json,
                    redaction_value,
                )
                if row is None:
                    raise RuntimeError("Failed to create session event")
                return cast(int, row["event_id"])
            except Exception:
                logger.exception("Failed to add session event")
                raise

    async def get_events_for_session(
        self,
        memory_session_id: str,
        kinds: Optional[list[EventKind]] = None,
    ) -> list[SessionEvent]:
        """Retrieve events for a session."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                if kinds:
                    placeholders = ", ".join(f"${i + 2}" for i in range(len(kinds)))
                    query = (
                        f"SELECT * FROM session_events WHERE memory_session_id = $1 "
                        f"AND kind IN ({placeholders}) ORDER BY timestamp ASC"
                    )
                    kind_values = [self._enum_to_value(k) for k in kinds]
                    rows = await conn.fetch(query, memory_session_id, *kind_values)
                else:
                    rows = await conn.fetch(
                        "SELECT * FROM session_events WHERE memory_session_id = $1 ORDER BY timestamp ASC",
                        memory_session_id,
                    )
                return [self._row_to_event(row) for row in rows]
            except Exception:
                logger.exception("Failed to fetch session events")
                raise

    async def store_observation(
        self,
        memory_session_id: str,
        type: ObservationType,
        title: str,
        subtitle: Optional[str] = None,
        facts_json: Optional[dict[str, object]] = None,
        narrative: Optional[str] = None,
        concepts_json: Optional[list[str]] = None,
        files_json: Optional[list[str]] = None,
        vector_ref: Optional[str] = None,
    ) -> int:
        """Store an observation extracted from a session."""
        timestamp = self._now_datetime()
        type_value = type.value if hasattr(type, "value") else str(type)

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO observations (
                        memory_session_id, timestamp, type, title, subtitle, facts_json,
                        narrative, concepts_json, files_json, vector_ref
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING obs_id
                    """,
                    memory_session_id,
                    timestamp,
                    type_value,
                    title,
                    subtitle,
                    facts_json,
                    narrative,
                    concepts_json,
                    files_json,
                    vector_ref,
                )
                if row is None:
                    raise RuntimeError("Failed to store observation")
                return cast(int, row["obs_id"])
            except Exception:
                logger.exception("Failed to store observation")
                raise

    async def get_observations_for_session(
        self, memory_session_id: str
    ) -> list[CrossObservation]:
        """Retrieve observations for a session."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    """
                    SELECT * FROM observations
                    WHERE memory_session_id = $1
                    ORDER BY timestamp ASC
                    """,
                    memory_session_id,
                )
                return [self._row_to_observation(row) for row in rows]
            except Exception:
                logger.exception("Failed to fetch observations for session")
                raise

    async def get_recent_observations(
        self,
        project: str,
        limit: int = 50,
        types: Optional[list[ObservationType]] = None,
    ) -> list[CrossObservation]:
        """Get recent observations for a project."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                if types:
                    placeholders = ", ".join(f"${i + 2}" for i in range(len(types)))
                    query = (
                        """
                        SELECT observations.* FROM observations
                        JOIN sessions ON sessions.memory_session_id = observations.memory_session_id
                        WHERE sessions.project = $1
                        """
                        f"AND observations.type IN ({placeholders}) "
                        "ORDER BY observations.timestamp DESC LIMIT $"
                        f"{len(types) + 2}"
                    )
                    type_values = [t.value if hasattr(t, "value") else str(t) for t in types]
                    rows = await conn.fetch(query, project, *type_values, limit)
                else:
                    rows = await conn.fetch(
                        """
                        SELECT observations.* FROM observations
                        JOIN sessions ON sessions.memory_session_id = observations.memory_session_id
                        WHERE sessions.project = $1
                        ORDER BY observations.timestamp DESC LIMIT $2
                        """,
                        project,
                        limit,
                    )
                return [self._row_to_observation(row) for row in rows]
            except Exception:
                logger.exception("Failed to fetch recent observations")
                raise

    async def get_observations_by_ids(self, obs_ids: list[int]) -> list[CrossObservation]:
        """Get observations by IDs."""
        if not obs_ids:
            return []

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                placeholders = ", ".join(f"${i + 1}" for i in range(len(obs_ids)))
                query = f"SELECT * FROM observations WHERE obs_id IN ({placeholders})"
                rows = await conn.fetch(query, *obs_ids)
                return [self._row_to_observation(row) for row in rows]
            except Exception:
                logger.exception("Failed to fetch observations by ids")
                raise

    async def store_summary(
        self,
        memory_session_id: str,
        request: Optional[str] = None,
        investigated: Optional[str] = None,
        learned: Optional[str] = None,
        completed: Optional[str] = None,
        next_steps: Optional[str] = None,
        vector_ref: Optional[str] = None,
    ) -> int:
        """Store a session summary."""
        timestamp = self._now_datetime()

        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO session_summaries (
                        memory_session_id, timestamp, request, investigated,
                        learned, completed, next_steps, vector_ref
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING summary_id
                    """,
                    memory_session_id,
                    timestamp,
                    request,
                    investigated,
                    learned,
                    completed,
                    next_steps,
                    vector_ref,
                )
                if row is None:
                    raise RuntimeError("Failed to store session summary")
                return cast(int, row["summary_id"])
            except Exception:
                logger.exception("Failed to store session summary")
                raise

    async def get_summary_for_session(
        self, memory_session_id: str
    ) -> Optional[SessionSummary]:
        """Retrieve summary for a session."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM session_summaries
                    WHERE memory_session_id = $1
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    memory_session_id,
                )
                return self._row_to_summary(row) if row else None
            except Exception:
                logger.exception("Failed to fetch session summary")
                raise

    async def get_recent_summaries(
        self, project: str, limit: int = 10
    ) -> list[SessionSummary]:
        """Get recent summaries for a project."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    """
                    SELECT session_summaries.* FROM session_summaries
                    JOIN sessions ON sessions.memory_session_id = session_summaries.memory_session_id
                    WHERE sessions.project = $1
                    ORDER BY session_summaries.timestamp DESC
                    LIMIT $2
                    """,
                    project,
                    limit,
                )
                return [self._row_to_summary(row) for row in rows]
            except Exception:
                logger.exception("Failed to fetch recent summaries")
                raise

    # Helper methods

    def _row_to_session(self, row: asyncpg.Record) -> SessionRecord:
        """Convert database row to SessionRecord."""
        data = dict(row)
        data["status"] = self._coerce_enum(SessionStatus, data.get("status"))

        # Handle datetime conversion from database
        if "started_at" in data and isinstance(data["started_at"], datetime):
            pass  # Already datetime
        if "ended_at" in data and isinstance(data["ended_at"], datetime):
            pass  # Already datetime

        # Handle metadata_json - convert to string if needed
        if "metadata_json" in data and data["metadata_json"] is not None:
            if not isinstance(data["metadata_json"], str):
                data["metadata_json"] = json.dumps(data["metadata_json"])

        return self._build_model(SessionRecord, data)

    def _row_to_event(self, row: asyncpg.Record) -> SessionEvent:
        """Convert database row to SessionEvent."""
        data = dict(row)
        data["kind"] = self._coerce_enum(EventKind, data.get("kind"))
        data["redaction_level"] = self._coerce_enum(
            RedactionLevel, data.get("redaction_level")
        )

        # Handle payload_json - convert to string if needed
        if "payload_json" in data and data["payload_json"] is not None:
            if not isinstance(data["payload_json"], str):
                data["payload_json"] = json.dumps(data["payload_json"])

        return self._build_model(SessionEvent, data)

    def _row_to_observation(self, row: asyncpg.Record) -> CrossObservation:
        """Convert database row to CrossObservation."""
        data = dict(row)
        data["type"] = self._coerce_enum(ObservationType, data.get("type"))

        # Handle JSON fields - convert to string if needed
        for json_field in ["facts_json", "concepts_json", "files_json"]:
            if json_field in data and data[json_field] is not None:
                if not isinstance(data[json_field], str):
                    data[json_field] = json.dumps(data[json_field])

        return self._build_model(CrossObservation, data)

    def _row_to_summary(self, row: asyncpg.Record) -> SessionSummary:
        """Convert database row to SessionSummary."""
        data = dict(row)
        return self._build_model(SessionSummary, data)

    @staticmethod
    def _now_datetime() -> datetime:
        """Get current UTC datetime."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _now_iso() -> str:
        """Get current UTC datetime as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _build_model(model_cls, data: dict[str, Any]) -> Any:
        """Build a model instance from data dict, filtering to allowed fields."""
        if hasattr(model_cls, "model_fields"):
            allowed = set(model_cls.model_fields.keys())
        elif hasattr(model_cls, "__fields__"):
            allowed = set(model_cls.__fields__.keys())
        elif hasattr(model_cls, "__dataclass_fields__"):
            allowed = set(model_cls.__dataclass_fields__.keys())
        elif hasattr(model_cls, "__annotations__"):
            allowed = set(model_cls.__annotations__.keys())
        else:
            return model_cls(**data)
        filtered = {key: value for key, value in data.items() if key in allowed}
        return model_cls(**filtered)

    @staticmethod
    def _coerce_enum(enum_cls: type, value: Any) -> Any:
        """Coerce a value to an enum type."""
        if value is None:
            return None
        if isinstance(value, enum_cls):
            return value
        if isinstance(value, str):
            try:
                return enum_cls(value)
            except Exception:
                return value
        return value

    @staticmethod
    def _enum_to_value(value: Any, default: Optional[str] = None) -> Optional[str]:
        """Convert enum to its string value."""
        if value is None:
            return default
        value_attr = getattr(value, "value", None)
        if value_attr is not None:
            return str(value_attr)
        return str(value)


# Import enum for _coerce_enum
import enum