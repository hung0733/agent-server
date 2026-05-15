from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from typing import Any, Callable

from dotenv import load_dotenv
from sqlalchemy import text

from backend.channels import EvolutionWhatsAppChannel
from backend.channels.evolution_handler import run_whatsapp_listener
from backend.db.session import engine
from backend.i18n import t
from logger_setup import setup_logging

logger = logging.getLogger(__name__)


async def check_database(db_engine: Any = engine) -> None:
    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception:
        logger.exception(t("main.db_health_check_failed"))
        raise

    logger.info(t("main.db_health_check_ok"))


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
    shutdown_event: asyncio.Event | None = None,
) -> None:
    load_dotenv()
    setup_logging_func()
    logger.info(t("main.startup"))

    await check_database(db_engine)

    channel = channel_factory()
    shutdown_event = shutdown_event or asyncio.Event()
    _install_signal_handlers(shutdown_event)

    listener_task = asyncio.create_task(run_whatsapp_listener(channel))
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
        await channel.close()
        await db_engine.dispose()
        logger.info(t("main.shutdown_complete"))


if __name__ == "__main__":
    asyncio.run(main())
