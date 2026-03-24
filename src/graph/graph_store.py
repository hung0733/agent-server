import logging
from i18n import _
from typing import Any
from urllib.parse import quote

from utils.tools import Tools

logger = logging.getLogger(__name__)


class GraphStore:
    checkpointer: Any = None
    pool: Any = None

    @staticmethod
    async def init_langgraph_checkpointer():
        """Initialize LangGraph AsyncPostgresSaver and run schema migrations.

        Returns an AsyncConnectionPool-backed checkpointer for use across
        the application lifetime. Caller is responsible for closing the pool.
        """
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        dsn = GraphStore._build_langgraph_dsn()

        pool = AsyncConnectionPool(
            conninfo=dsn,
            max_size=20,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        await pool.open()

        # Ensure the langgraph schema exists before setup() creates tables
        schema = Tools.require_env("LANGGRAPH_SCHEMA")
        async with pool.connection() as conn:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')  # type: ignore

        checkpointer = AsyncPostgresSaver(conn=pool)  # type: ignore
        await checkpointer.setup()

        GraphStore.checkpointer = checkpointer
        GraphStore.pool = pool

        logger.info(
            _("LangGraph checkpointer initialized (schema=%s)"),
            Tools.require_env("LANGGRAPH_SCHEMA"),
        )
        return checkpointer, pool

    @staticmethod
    def _build_langgraph_dsn() -> str:
        """Build a psycopg3-compatible DSN with LANGGRAPH_SCHEMA as search_path."""
        host = Tools.require_env("POSTGRES_HOST")
        port = Tools.require_env("POSTGRES_PORT")
        user = Tools.require_env("POSTGRES_USER")
        password = Tools.require_env("POSTGRES_PASSWORD")
        database = Tools.require_env("POSTGRES_DB")
        schema = Tools.require_env("LANGGRAPH_SCHEMA")

        options_val = quote(f"-c search_path={schema},public", safe="")
        return f"postgresql://{user}:{password}@{host}:{port}/{database}?options={options_val}"
