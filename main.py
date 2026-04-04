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
from aiohttp import web

from graph.graph_store import GraphStore
from utils.tools import Tools

load_dotenv()


sys.path.insert(0, "src")
from logging_setup import setup_logging

_log_level = logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO
setup_logging(level=_log_level)
from i18n import _

logger = logging.getLogger(__name__)


async def _wait_for_background_tasks() -> None:
    await Tools.wait_task_comp()


async def main() -> None:
    api_runner: web.AppRunner | None = None
    from utils.db_pool import configure_pool, close_pool
    from msg_queue.manager import get_queue_manager
    from msg_queue.handler import register_all_handlers
    from msg_queue.dedup import MessageDeduplicator
    from channels.whatsapp import WhatsAppChannel, WhatsAppWSClient
    from scheduler.task_scheduler import TaskScheduler
    from api.app import create_app

    # Init asyncpg pool (used by DAOs / SQLAlchemy layer)
    await configure_pool()
    logger.info(_("asyncpg pool initialized"))

    # Init LangGraph checkpointer
    checkpointer, lg_pool = await GraphStore.init_langgraph_checkpointer()

    # Init message queue
    qm = get_queue_manager()
    register_all_handlers(qm)
    qm.start()

    # Init Task Scheduler (background service for scheduled tasks)
    scheduler = TaskScheduler()
    scheduler_task = None
    if os.getenv("SCHEDULER_ENABLED", "true").lower() == "true":
        scheduler_task = asyncio.create_task(scheduler.start())
        logger.info(_("Task scheduler started"))
    else:
        logger.info(_("Task scheduler is disabled"))

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

    if os.getenv("HTTP_ENABLED", "true").lower() == "true":
        api_app = create_app(qm, wa_dedup)
        api_runner = web.AppRunner(api_app)
        await api_runner.setup()
        host = os.getenv("HTTP_HOST", "0.0.0.0")
        port = int(os.getenv("HTTP_PORT", "8080"))
        site = web.TCPSite(api_runner, host=host, port=port)
        await site.start()
        logger.info(_("HTTP server started on %s:%d"), host, port)
    else:
        logger.info(_("HTTP server is disabled"))

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

    # Stop scheduler first
    if scheduler_task is not None:
        await scheduler.stop()
        try:
            await asyncio.wait_for(scheduler_task, timeout=5)
        except asyncio.TimeoutError:
            logger.warning(_("Task scheduler did not stop within 5s"))
            scheduler_task.cancel()

    # Stop accepting new inbound messages
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
    await _wait_for_background_tasks()
    if api_runner is not None:
        await api_runner.cleanup()
    await lg_pool.close()
    await close_pool()
    logger.info(_("Shutdown complete"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
