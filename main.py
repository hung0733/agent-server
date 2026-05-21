from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import text

from backend.channels import EvolutionWhatsAppChannel
from backend.channels.evolution_handler import run_whatsapp_listener
from backend.db.session import engine
from backend.graph.graph_store import GraphStore
from backend.i18n import t
from backend.queues.message_queue import MessageQueue
from backend.queues.msg_queue_handle import handle_agent_message
from backend.tdai_memory import MemoryConfig, MemoryManager
from logger_setup import setup_logging

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


async def check_database(db_engine: Any = engine) -> None:
    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception:
        logger.exception(t("main.db_health_check_failed"))
        raise

    logger.info(t("main.db_health_check_ok"))


async def upgrade_database_schema() -> None:
    logger.info(t("main.db_schema_upgrade_started"))
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    alembic_cfg.attributes["configure_logger"] = False
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    logger.info(t("main.db_schema_upgrade_completed"))


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, shutdown_event.set)


async def main(
    *,
    db_engine: Any = engine,
    channel_factory: Callable[[], EvolutionWhatsAppChannel] = EvolutionWhatsAppChannel,
    setup_logging_func: Callable[[], None] = setup_logging,
    upgrade_database_schema_func: Callable[[], Awaitable[Any]] = upgrade_database_schema,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    load_dotenv()
    setup_logging_func()
    logger.info(t("main.startup"))

    await check_database(db_engine)
    await upgrade_database_schema_func()
    await GraphStore.init_langgraph_checkpointer()

    memory_manager: MemoryManager | None = None
    logger.info(t("main.memory_initialize_started"))
    try:
        memory_manager = MemoryManager(MemoryConfig.from_env())
        await memory_manager.initialize()
    except Exception:
        logger.exception(t("main.memory_initialize_failed"))
        raise
    logger.info(t("main.memory_initialize_completed"))

    channel = channel_factory()
    message_queue = MessageQueue(handle_agent_message, max_concurrency=2)
    message_queue.start()
    shutdown_event = shutdown_event or asyncio.Event()
    _install_signal_handlers(shutdown_event)

    listener_task = asyncio.create_task(
        run_whatsapp_listener(channel, message_queue=message_queue)
    )
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    try:
        done, pending = await asyncio.wait(
            {listener_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if listener_task in done:
            await listener_task
        if shutdown_task in done:
            logger.info(t("main.shutdown_requested"))
    finally:
        listener_task.cancel()
        shutdown_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task
        with suppress(asyncio.CancelledError):
            await shutdown_task
        await message_queue.stop()
        await channel.close()
        if memory_manager is not None:
            await memory_manager.destroy()
            logger.info(t("main.memory_destroy_completed"))
        await db_engine.dispose()
        await GraphStore.pool.close()
        logger.info(t("main.shutdown_complete"))


if __name__ == "__main__":
    asyncio.run(main())
