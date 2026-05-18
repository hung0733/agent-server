import logging
import os
from typing import Any

from urllib.parse import quote

from backend.i18n import t

logger = logging.getLogger(__name__)


class GraphStore:
    checkpointer: Any = None
    pool: Any = None

    @staticmethod
    async def init_langgraph_checkpointer(use_test_schema: bool = False):
        """Initialize LangGraph AsyncPostgresSaver and run schema migrations.

        Returns an AsyncConnectionPool-backed checkpointer for use across
        the application lifetime. Caller is responsible for closing the pool.
        """
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        dsn = GraphStore._build_langgraph_dsn(use_test_schema=use_test_schema)

        pool = AsyncConnectionPool(
            conninfo=dsn,
            max_size=20,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        await pool.open()

        # Ensure the langgraph schema exists before setup() creates tables
        schema = GraphStore._get_langgraph_schema(use_test_schema=use_test_schema)
        async with pool.connection() as conn:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')  # type: ignore

        checkpointer = AsyncPostgresSaver(conn=pool)  # type: ignore
        await checkpointer.setup()

        GraphStore.checkpointer = checkpointer
        GraphStore.pool = pool

        logger.info(
            t("graph.store.checkpointer_initialized"),
            schema,
        )
        return checkpointer, pool

    @staticmethod
    def _build_langgraph_dsn(use_test_schema: bool = False) -> str:
        """Build a psycopg3-compatible DSN with the LangGraph search_path."""
        host = _require_env("POSTGRES_HOST")
        port = _require_env("POSTGRES_PORT")
        user = _require_env("POSTGRES_USER")
        password = _require_env("POSTGRES_PASSWORD")
        database = _require_env("POSTGRES_DB")
        schema = GraphStore._get_langgraph_schema(use_test_schema=use_test_schema)

        options_val = quote(f"-c search_path={schema},public", safe="")
        return f"postgresql://{user}:{password}@{host}:{port}/{database}?options={options_val}"

    @staticmethod
    def _get_langgraph_schema(use_test_schema: bool = False) -> str:
        if use_test_schema:
            return _require_env("TEST_LANGGRAPH_SCHEMA")
        return _require_env("LANGGRAPH_SCHEMA")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(t("graph.store.missing_config"))
    return value
