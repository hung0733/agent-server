"""Agent Server entry point.

Initializes database connections (asyncpg pool + LangGraph checkpointer)
using configuration from .env, then starts the application.
"""

from __future__ import annotations

import sys
import asyncio
import logging
import os
import signal

from dotenv import load_dotenv

from graph.graph_store import GraphStore
from utils.tools import Tools

load_dotenv()


sys.path.insert(0, "src")
from src.logging_setup import setup_logging

_log_level = logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO
setup_logging(level=_log_level)
from src.i18n import _

logger = logging.getLogger(__name__)


async def main() -> None:
    from src.utils.db_pool import configure_pool, close_pool
    from src.msg_queue.manager import get_queue_manager
    from src.msg_queue.handler import register_all_handlers
    from src.msg_queue.dedup import MessageDeduplicator
    from src.channels.whatsapp import WhatsAppChannel, WhatsAppWSClient

    # Init asyncpg pool (used by DAOs / SQLAlchemy layer)
    await configure_pool()
    logger.info(_("asyncpg pool initialized"))

    # Init LangGraph checkpointer
    checkpointer, lg_pool = await GraphStore.init_langgraph_checkpointer()

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

    # Use signal handlers so shutdown runs in a clean (non-cancelled) context.
    # loop.add_signal_handler() intercepts SIGINT/SIGTERM before Python can
    # raise KeyboardInterrupt, so the finally block can safely await.
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info(_("Agent server started — waiting for messages"))
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        # asyncio.run() cancels the main task on KeyboardInterrupt.
        # Uncancel so the cleanup awaits below work normally.
        t = asyncio.current_task()
        if t is not None:
            t.uncancel()

    logger.info(_("Shutdown signal received — draining queue"))
    # Stop accepting new inbound messages first
    await wa_client.stop()

    # Wait for in-flight tasks to finish (max 30 s)
    drain_timeout = float(os.getenv("SHUTDOWN_DRAIN_TIMEOUT", "30"))
    try:
        await qm.wait_for_completion(timeout=drain_timeout)
    except asyncio.TimeoutError:
        logger.warning(
            _("Queue drain timed out after %ds — forcing shutdown"), int(drain_timeout)
        )

    qm.stop()
    Tools.wait_task_comp()
    await lg_pool.close()
    await close_pool()
    logger.info(_("Shutdown complete"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
