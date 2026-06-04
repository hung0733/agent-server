from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.channels import EvolutionWhatsAppChannel
from backend.channels.evolution_media import build_evolution_files
from backend.channels.types import ReceivedMessage, WhatsAppInboundMessage
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.queues.message_queue import FilePayload, MessageQueue, MsgQueueTask
from backend.services.whatsapp_session import resolve_whatsapp_agent_session

logger = logging.getLogger(__name__)


class WhatsAppMsgQueueTask(MsgQueueTask):
    def __init__(
        self,
        *,
        message: str,
        agent_id: str,
        session_id: str,
        files: list[FilePayload] | None = None,
        channel: EvolutionWhatsAppChannel | None = None,
        phone_no: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            agent_id=agent_id,
            session_id=session_id,
            files=files,
        )
        self._channel = channel
        self._phone_no = phone_no
        self._response_parts: list[str] = []
        self._tool_parts: list[str] = []
        self._last_sent_message_id: str | None = None

    async def callback(self, chunk: StreamChunk) -> str | None:
        if chunk.chunk_type == "interrupt":
            return await self._handle_interrupt(chunk)

        if chunk.chunk_type == "content" and chunk.content:
            self._response_parts.append(chunk.content)
            return None

        if chunk.chunk_type == "tool" and chunk.content:
            self._tool_parts.append(
                t("channels.evolution.tool_called_reply") % chunk.content
            )
            return None

        if chunk.chunk_type in {"text_end", "done", "task_end"}:
            await self._flush_tool_parts()
            return await self._flush_response_parts()

    async def _handle_interrupt(self, chunk: StreamChunk) -> str | None:
        interrupt_data = chunk.data or {}
        interrupt_msg = str(interrupt_data.get("message") or chunk.content or "")

        if interrupt_msg and self._channel and self._phone_no:
            resp = await self._channel.send_text(self._phone_no, interrupt_msg)
            return self._extract_message_id(resp)

    async def _flush_response_parts(self) -> str | None:
        if not self._response_parts:
            return None

        response_text = "".join(self._response_parts)
        self._response_parts.clear()
        await self._send_text(response_text)

    async def _flush_tool_parts(self) -> None:
        if not self._tool_parts:
            return

        tool_text = "".join(self._tool_parts)
        self._tool_parts.clear()
        await self._send_text(tool_text)

    async def _send_text(self, response_text: str) -> None:
        if not response_text:
            return

        if self._channel and self._phone_no:
            started_at = time.perf_counter()
            logger.info(
                t("channels.evolution.reply_send_started"),
                self._phone_no,
                len(response_text),
            )
            resp = await self._channel.send_text(self._phone_no, response_text)
            self._last_sent_message_id = self._extract_message_id(resp)
            logger.info(
                t("channels.evolution.reply_send_completed"),
                self._phone_no,
                round((time.perf_counter() - started_at) * 1000),
            )

    @staticmethod
    def _extract_message_id(evolution_response: dict[str, Any]) -> str | None:
        if not isinstance(evolution_response, dict):
            return None
        key = evolution_response.get("key")
        if isinstance(key, dict):
            return key.get("id")
        return None


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


async def enrich_received_message(message: ReceivedMessage) -> ReceivedMessage:
    message.agent_id, message.session_id = await resolve_whatsapp_agent_session(message)
    return message


async def apply_quoted_message_fallback(
    message: ReceivedMessage,
    channel: EvolutionWhatsAppChannel | None = None,
) -> ReceivedMessage:
    if message.quoted_message_id:
        _log_quoted_message_source(message, "payload_context_info")
        return message
    if not channel:
        _log_quoted_message_source(message, "none")
        return message
    if not message.instance or not message.message_id:
        _log_quoted_message_source(message, "none")
        return message
    if not hasattr(channel, "find_message_quoted_message_id"):
        _log_quoted_message_source(message, "none")
        return message

    reply_channel = _build_reply_channel(channel, message.instance)
    if not reply_channel:
        _log_quoted_message_source(message, "none")
        return message

    try:
        message.quoted_message_id = await reply_channel.find_message_quoted_message_id(
            message.message_id
        )
        _log_quoted_message_source(
            message,
            "evolution_find_message" if message.quoted_message_id else "none",
        )
    except Exception:
        logger.warning(
            t("channels.evolution.quoted_message_fallback_failed"),
            message.instance,
            message.remote_jid,
            exc_info=True,
        )
    return message


async def resolve_resume_message_id(
    message: ReceivedMessage,
    channel: EvolutionWhatsAppChannel | None = None,
) -> str | None:
    if message.quoted_message_id:
        return message.quoted_message_id
    if not channel or not message.remote_jid:
        return None
    if not hasattr(channel, "find_latest_outbound_message_id"):
        return None

    reply_channel = _build_reply_channel(channel, message.instance)
    if not reply_channel:
        return None

    try:
        latest_message_id = await reply_channel.find_latest_outbound_message_id(
            message.remote_jid
        )
        logger.info(
            t("channels.evolution.latest_outbound_message_id_resolved"),
            message.instance,
            message.remote_jid,
            message.message_id,
            latest_message_id,
        )
        return latest_message_id
    except Exception:
        logger.warning(
            t("channels.evolution.latest_outbound_message_lookup_failed"),
            message.instance,
            message.remote_jid,
            exc_info=True,
        )
    return None


def _log_quoted_message_source(message: ReceivedMessage, source: str) -> None:
    logger.info(
        t("channels.evolution.quoted_message_id_resolved"),
        message.instance,
        message.remote_jid,
        message.message_id,
        message.quoted_message_id,
        source,
    )


async def build_msg_queue_task(
    message: ReceivedMessage,
    *,
    channel: EvolutionWhatsAppChannel | None = None,
    http_client: httpx.AsyncClient | None = None,
    resume_value: Any = None,
) -> MsgQueueTask | None:
    if not message.agent_id or not message.session_id:
        logger.warning(
            t("channels.evolution.message_queue_missing_required_fields"),
            message.agent_id,
            message.session_id,
            message.message_id,
        )
        return None

    files = await build_evolution_files(message, http_client=http_client)
    return WhatsAppMsgQueueTask(
        message=message.content or "",
        agent_id=message.agent_id,
        session_id=message.session_id,
        files=files,
        channel=channel,
        phone_no=message.phone_no,
    )


async def log_inbound_message(
    message: WhatsAppInboundMessage,
    message_queue: MessageQueue | None = None,
    *,
    channel: EvolutionWhatsAppChannel | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    received_message = EvolutionWhatsAppChannel().to_received_message(message)
    await enrich_received_message(received_message)
    await apply_quoted_message_fallback(received_message, channel)

    if message_queue:
        reply_channel = _build_reply_channel(channel, received_message.instance)
        task = await build_msg_queue_task(
            received_message,
            channel=reply_channel,
            http_client=http_client,
        )
        if task:
            resume_message_id = await resolve_resume_message_id(
                received_message, reply_channel
            )
            if resume_message_id:
                resumed = await message_queue.resume_interrupt(
                    task.agent_id, resume_message_id, task
                )
                if resumed:
                    log_received_message(received_message)
                    return
            await message_queue.enqueue(task)
    log_received_message(received_message)


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
    message_queue: MessageQueue | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    logger.info(t("main.whatsapp_listener_started"))
    async for message in channel.listen_messages():
        await log_inbound_message(
            message,
            message_queue,
            channel=channel,
            http_client=http_client,
        )
