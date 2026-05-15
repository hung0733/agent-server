from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from typing import Any, Callable

from dotenv import load_dotenv
from sqlalchemy import text

from backend.channels import EvolutionWhatsAppChannel
from backend.channels.types import ReceivedMessage, WhatsAppInboundMessage
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


def extract_message_metadata(
    message: WhatsAppInboundMessage,
) -> tuple[str | None, str | None]:
    data = message.data if isinstance(message.data, dict) else {}
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    message_id = key.get("id") or data.get("messageId")
    remote_jid = (
        key.get("remoteJid") or data.get("remoteJid") or message.raw.get("sender")
    )
    return message_id, remote_jid


def log_inbound_message(message: WhatsAppInboundMessage) -> None:
    received_message = EvolutionWhatsAppChannel().to_received_message(message)
    log_received_message(received_message)


def log_received_message(message: ReceivedMessage) -> None:
    logger.info(
        t("main.whatsapp_message_received"),
        message.instance,
        message.message_id,
        message.remote_jid,
        message.phone_no,
        message.content_type,
        message.has_text,
        message.has_media,
    )


async def run_whatsapp_listener(channel: EvolutionWhatsAppChannel) -> None:
    logger.info(t("main.whatsapp_listener_started"))
    async for message in channel.listen_messages():
        log_inbound_message(message)


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
