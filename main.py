"""Agent Server entry point.

Initializes database connections (asyncpg pool + LangGraph checkpointer)
using configuration from .env, then starts the application.
"""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.insert(0, "src")
from src.logging_setup import setup_logging
_log_level = logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO
setup_logging(level=_log_level)
from src.i18n import _

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


def _build_langgraph_dsn() -> str:
    """Build a psycopg3-compatible DSN with LANGGRAPH_SCHEMA as search_path."""
    host = _require_env("POSTGRES_HOST")
    port = _require_env("POSTGRES_PORT")
    user = _require_env("POSTGRES_USER")
    password = _require_env("POSTGRES_PASSWORD")
    database = _require_env("POSTGRES_DB")
    schema = _require_env("LANGGRAPH_SCHEMA")

    options_val = quote(f"-c search_path={schema},public", safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?options={options_val}"


async def init_langgraph_checkpointer():
    """Initialize LangGraph AsyncPostgresSaver and run schema migrations.

    Returns an AsyncConnectionPool-backed checkpointer for use across
    the application lifetime. Caller is responsible for closing the pool.
    """
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = _build_langgraph_dsn()

    pool = AsyncConnectionPool(
        conninfo=dsn,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()

    # Ensure the langgraph schema exists before setup() creates tables
    schema = _require_env("LANGGRAPH_SCHEMA")
    async with pool.connection() as conn:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    checkpointer = AsyncPostgresSaver(conn=pool) # type: ignore
    await checkpointer.setup()

    logger.info(_("LangGraph checkpointer initialized (schema=%s)"), _require_env("LANGGRAPH_SCHEMA"))
    return checkpointer, pool


async def main() -> None:
    from src.tools.db_pool import configure_pool, close_pool
    from src.msg_queue.manager import get_queue_manager
    from src.msg_queue.handler import register_all_handlers
    from src.msg_queue.dedup import MessageDeduplicator
    from src.channels.whatsapp import WhatsAppChannel, WhatsAppWSClient

    # Init asyncpg pool (used by DAOs / SQLAlchemy layer)
    await configure_pool()
    logger.info(_("asyncpg pool initialized"))

    # Init LangGraph checkpointer
    checkpointer, lg_pool = await init_langgraph_checkpointer()

    # Init message queue
    qm = get_queue_manager()
    register_all_handlers(qm)
    qm.start()

    # Init WhatsApp listener (global mode — receives all instances)
    wa_channel = WhatsAppChannel()
    wa_dedup = MessageDeduplicator()
    wa_client = WhatsAppWSClient(
        queue=qm,
        channel=wa_channel,
        dedup=wa_dedup,
    )
    await wa_client.start()
    logger.info(_("WhatsApp listener started (global mode)"))

    try:
        logger.info(_("Agent server started — waiting for messages"))
        await asyncio.Event().wait()  # block until interrupted
    finally:
        await wa_client.stop()
        qm.stop()
        await lg_pool.close()
        await close_pool()
        logger.info(_("Shutdown complete"))


if __name__ == "__main__":
    asyncio.run(main())
