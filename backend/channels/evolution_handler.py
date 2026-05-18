from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx

from backend.channels import EvolutionWhatsAppChannel
from backend.channels.evolution_media import build_evolution_files
from backend.channels.types import ReceivedMessage, WhatsAppInboundMessage
from backend.i18n import t
from backend.queues.message_queue import LLMStreamHandler, MessagePayload, MessageQueue
from backend.services.whatsapp_session import resolve_whatsapp_agent_session


logger = logging.getLogger(__name__)


def extract_message_metadata(
    message: WhatsAppInboundMessage,
) -> tuple[str | None, str | None]:
    data = message.data if isinstance(message.data, dict) else {}
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    message_id = key.get("id") or data.get("messageId")
    remote_jid = key.get("remoteJid") or data.get("remoteJid") or message.raw.get("sender")
    return message_id, remote_jid


async def enrich_received_message(message: ReceivedMessage) -> ReceivedMessage:
    message.agent_id, message.session_id = await resolve_whatsapp_agent_session(message)
    return message


async def build_llm_message_payload(
    message: ReceivedMessage,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> MessagePayload | None:
    if not message.agent_id or not message.session_id:
        logger.warning(
            t("channels.evolution.message_queue_missing_required_fields"),
            message.agent_id,
            message.session_id,
            message.message_id,
        )
        return None

    files = await build_evolution_files(message, http_client=http_client)
    return {
        "agent_id": message.agent_id,
        "session_id": message.session_id,
        "message": message.content or "",
        "files": files,
    }


async def log_inbound_message(
    message: WhatsAppInboundMessage,
    message_queue: MessageQueue | None = None,
    *,
    channel: EvolutionWhatsAppChannel | None = None,
    stream_tasks: set[asyncio.Task[None]] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    received_message = EvolutionWhatsAppChannel().to_received_message(message)
    await enrich_received_message(received_message)
    if message_queue:
        payload = await build_llm_message_payload(received_message, http_client=http_client)
        if payload:
            task = asyncio.create_task(
                _drain_message_stream(
                    message_queue,
                    payload,
                    channel=_build_reply_channel(channel, received_message.instance),
                    phone_no=received_message.phone_no,
                )
            )
            if stream_tasks is not None:
                stream_tasks.add(task)
                task.add_done_callback(stream_tasks.discard)
    log_received_message(received_message)


async def _drain_message_stream(
    message_queue: MessageQueue,
    payload: MessagePayload,
    *,
    channel: EvolutionWhatsAppChannel | None = None,
    phone_no: str | None = None,
) -> None:
    response_parts: list[str] = []
    async for chunk in message_queue.create_msg_queue(payload):
        if chunk.chunk_type == "content" and chunk.content:
            response_parts.append(chunk.content)

    response_text = "".join(response_parts)
    if channel and phone_no and response_text:
        await channel.send_text(phone_no, response_text)


def _build_reply_channel(
    channel: EvolutionWhatsAppChannel | None,
    instance: str | None,
) -> EvolutionWhatsAppChannel | None:
    if not channel or not instance:
        return channel
    if not isinstance(channel, EvolutionWhatsAppChannel):
        return channel
    if channel.whatsapp_instance == instance:
        return channel
    return EvolutionWhatsAppChannel(
        whatsapp_instance=instance,
        whatsapp_key=channel.whatsapp_key or channel.global_api_key,
        api_url=channel.api_url,
        global_api_key=channel.global_api_key,
        http_client=channel._http_client,
    )


def log_received_message(message: ReceivedMessage) -> None:
    logger.info(
        t("main.whatsapp_message_received"),
        message.instance,
        message.agent_id,
        message.session_id,
        message.message_id,
        message.remote_jid,
        message.phone_no,
        message.content_type,
        message.has_text,
        message.has_media,
    )


async def run_whatsapp_listener(
    channel: EvolutionWhatsAppChannel,
    llm_stream_handler: LLMStreamHandler | None = None,
    *,
    message_queue_factory: Callable[[LLMStreamHandler], MessageQueue] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    logger.info(t("main.whatsapp_listener_started"))
    message_queue = None
    stream_tasks: set[asyncio.Task[None]] = set()
    if llm_stream_handler:
        if message_queue_factory:
            message_queue = message_queue_factory(llm_stream_handler)
        else:
            message_queue = MessageQueue(llm_stream_handler)
        message_queue.start()

    try:
        async for message in channel.listen_messages():
            await log_inbound_message(
                message,
                message_queue,
                channel=channel,
                stream_tasks=stream_tasks,
                http_client=http_client,
            )
    finally:
        if stream_tasks:
            await asyncio.gather(*stream_tasks, return_exceptions=True)
        if message_queue:
            await message_queue.stop()
