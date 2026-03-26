"""WhatsApp channel via Evolution API.

Two components:
  - WhatsAppChannel   : outbound REST sender (POST /message/sendText)
  - WhatsAppWSClient  : inbound Socket.IO listener (WEBSOCKET_GLOBAL_EVENTS=true)
                        One connection receives events from ALL registered instances.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncGenerator, Optional

import aiohttp
import socketio

from channels.base import AbstractChannel, ChannelType, IncomingMessage
from i18n import _
from msg_queue.handler import MsgQueueHandler
from msg_queue.models import StreamChunk

if TYPE_CHECKING:
    from msg_queue.manager import QueueManager
    from msg_queue.dedup import MessageDeduplicator

logger = logging.getLogger(__name__)

_WS_RECONNECT_DELAYS = [1, 2, 4, 8, 16]  # seconds, exponential backoff


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(_("Required environment variable '%s' is not set") % name)
    return value


class WhatsAppChannel(AbstractChannel):
    """Sends text messages via Evolution API REST endpoint."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._api_url = (api_url or _require_env("EVOLUTION_API_URL")).rstrip("/")
        self._api_key = api_key or _require_env("EVOLUTION_API_KEY")

    async def send_text(self, instance_id: str, recipient_id: str, text: str) -> None:
        """Send a plain-text WhatsApp message.

        Args:
            instance_id:  Evolution API instance name.
            recipient_id: Recipient phone number (international format, no +).
            text:         Message content.
        """
        url = f"{self._api_url}/message/sendText/{instance_id}"
        payload = {"number": recipient_id, "text": text}
        headers = {"apikey": self._api_key, "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error(
                        _("Evolution API send_text failed [%s]: %s"), resp.status, body
                    )
                else:
                    logger.debug(
                        _("Sent message to %s via instance %s"),
                        recipient_id,
                        instance_id,
                    )

    async def mark_message_read(
        self,
        instance_id: str,
        msg_id: str,
        remote_jid: str,
        api_key: Optional[str] = None,
    ) -> None:
        """Mark a received message as read.

        Args:
            instance_id: Evolution API instance name.
            msg_id:      Message ID (from the ``key.id`` field of the event).
            remote_jid:  Sender JID including suffix (e.g. ``628xxx@s.whatsapp.net``).
            api_key:     Per-instance API key; falls back to the global key when omitted.
        """
        url = f"{self._api_url}/chat/markMessageAsRead/{instance_id}"
        payload = {
            "readMessages": [{"id": msg_id, "fromMe": False, "remoteJid": remote_jid}]
        }
        headers = {
            "apikey": api_key or self._api_key,
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.warning(
                        _("Evolution API markMessageAsRead failed [%s]: %s"),
                        resp.status,
                        body,
                    )
                else:
                    logger.debug(
                        _("Marked message %s as read on instance %s"),
                        msg_id,
                        instance_id,
                    )

    @staticmethod
    def _clean_number(remote_jid: str) -> str:
        """Strip @s.whatsapp.net / @g.us suffix from JID."""
        return remote_jid.split("@")[0]


class WhatsAppWSClient:
    """Global Socket.IO listener for Evolution API (WEBSOCKET_GLOBAL_EVENTS=true).

    One connection receives events from ALL registered instances.
    The instance name is read from each event payload and used to route replies.
    Reconnects automatically with exponential backoff on disconnect.
    Duplicate messages are filtered via MessageDeduplicator.
    """

    def __init__(
        self,
        queue: "QueueManager",
        channel: WhatsAppChannel,
        dedup: "MessageDeduplicator",
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._queue = queue
        self._channel = channel
        self._dedup = dedup
        self._api_url = (api_url or _require_env("EVOLUTION_API_URL")).rstrip("/")
        self._api_key = api_key or _require_env("EVOLUTION_API_KEY")
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Spawn the Socket.IO listener as a background task."""
        self._task = asyncio.create_task(
            self._listen_loop(), name="sio-whatsapp-global"
        )

    async def stop(self) -> None:
        """Cancel the listener task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(_("WhatsAppWSClient stopped"))

    async def _listen_loop(self) -> None:
        """Outer loop: reconnects on failure with exponential backoff."""
        attempt = 0
        while True:
            try:
                await self._connect_and_receive()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = _WS_RECONNECT_DELAYS[
                    min(attempt, len(_WS_RECONNECT_DELAYS) - 1)
                ]
                logger.warning(
                    _("Socket.IO disconnected (attempt=%d): %s — retrying in %ds"),
                    attempt + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    async def _connect_and_receive(self) -> None:
        """Connect via Socket.IO and block until disconnected."""
        sio = socketio.AsyncClient(
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )

        disconnected = asyncio.Event()

        @sio.event
        async def connect() -> None:
            logger.info(_("Socket.IO connected to Evolution API (global mode)"))

        @sio.event
        async def disconnect() -> None:
            logger.warning(_("Socket.IO disconnected from Evolution API"))
            disconnected.set()

        # Evolution API emits both lowercase and uppercase event names
        @sio.on("messages.upsert")  # type: ignore
        async def on_messages_upsert(data: dict) -> None:
            await self._handle_raw("messages.upsert", data)

        @sio.on("MESSAGES_UPSERT")  # type: ignore
        async def on_messages_upsert_upper(data: dict) -> None:
            await self._handle_raw("MESSAGES_UPSERT", data)

        logger.debug(_("Socket.IO connecting: %s"), self._api_url)
        await sio.connect(
            self._api_url,
            headers={"apikey": self._api_key},
            transports=["websocket"],
            wait_timeout=10,
        )
        await disconnected.wait()
        await sio.disconnect()

    async def _handle_raw(self, event: str, data: dict) -> None:
        """Parse a Socket.IO event and enqueue if it's a valid inbound message."""
        # With WEBSOCKET_GLOBAL_EVENTS=true, Evolution API wraps data as:
        # { "instance": "<name>", "data": { ... } }
        # The instance name is used to route the reply back.
        instance_id: str = data.get("instance", "")
        inner_data = data.get("data", data)  # fallback: data IS the inner payload

        msg = self._parse_message(event, instance_id, inner_data)
        if msg is None:
            return

        if await self._dedup.is_duplicate(msg.id):
            logger.debug(_("Duplicate message dropped: %s"), msg.id)
            return
        await self._dedup.register(msg.id)

        sender_phone_no: str = msg.sender_id
        receiver_phone_no: str = msg.receiver_id

        logger.debug(
            _("Parsed message - sender_phone=%s, receiver_phone=%s, msg_id=%s"),
            sender_phone_no,
            receiver_phone_no,
            msg.id,
        )

        from db.dao.agent_instance_dao import AgentInstanceDAO

        logger.debug(
            _("Looking up agent instance - sender=%s, receiver=%s"),
            sender_phone_no,
            receiver_phone_no,
        )

        agent_instance = await AgentInstanceDAO.get_by_phones(
            sender_phone_no, receiver_phone_no
        )

        if agent_instance is None or agent_instance.agent_id is None:
            logger.warning(
                _("No agent instance found for phone %s — dropping message %s"),
                receiver_phone_no,
                msg.id,
            )
            logger.debug(
                _("Lookup failed - sender_phone=%s, receiver_phone=%s, agent_instance=%s"),
                sender_phone_no,
                receiver_phone_no,
                agent_instance,
            )
            return

        logger.debug(
            _("Agent instance found - id=%s, agent_id=%s, phone_no=%s, whatsapp_key=%s"),
            agent_instance.id,
            agent_instance.agent_id,
            agent_instance.phone_no,
            agent_instance.whatsapp_key[:10] + "..." if agent_instance.whatsapp_key else None,
        )

        whatsapp_key: str = agent_instance.whatsapp_key  # type: ignore[assignment]
        remote_jid = f"{msg.sender_id}@s.whatsapp.net"
        await self._channel.mark_message_read(
            msg.instance_id, msg.id, remote_jid, api_key=whatsapp_key
        )

        message: str = msg.text

        stream_generator: AsyncGenerator[StreamChunk, None] = (
            MsgQueueHandler.create_msg_queue(
                agent_id=agent_instance.agent_id,
                session_id=f"default-{agent_instance.agent_id[6:]}",
                message=message,
            )
        )

        logger.info(
            _("Queued message from %s via instance %s (id=%s)"),
            msg.sender_id,
            msg.instance_id,
            msg.id,
        )

        asyncio.create_task(
            self._consume_stream(stream_generator, msg),
            name=f"stream-{msg.id}",
        )

    async def _consume_stream(
        self,
        gen: "AsyncGenerator[StreamChunk, None]",
        msg: IncomingMessage,
    ) -> None:
        """Drain *gen*, accumulate content chunks, then reply via msg.callback."""
        reply_parts: list[str] = []

        try:
            async for chunk in gen:
                if chunk.chunk_type == "content" and chunk.content:
                    reply_parts.append(chunk.content)
                    
        except Exception:
            logger.exception(
                _("Stream error for message %s from %s"),
                msg.id,
                msg.sender_id,
            )
            return

        reply = "".join(reply_parts).strip()

        if not reply:
            logger.warning(
                _("Empty reply for message %s — skipping send"),
                msg.id,
            )
            return

        await msg.callback(reply)

    def _parse_message(
        self, event: str, instance_id: str, data: dict
    ) -> Optional[IncomingMessage]:
        """Parse event data into an IncomingMessage.

        Returns None for outbound messages, group messages, or non-text events.
        """
        import json
        logger.debug(
            _("_parse_message - event=%s, instance_id=%s, data_keys=%s"),
            event,
            instance_id,
            list(data.keys()),
        )

        # Safe JSON serialization - convert bytes to base64 string
        def _safe_serialize(obj):
            if isinstance(obj, bytes):
                import base64
                return f"<bytes:{base64.b64encode(obj).decode()[:50]}...>"
            elif isinstance(obj, dict):
                return {k: _safe_serialize(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_safe_serialize(item) for item in obj]
            else:
                return obj

        try:
            safe_data = _safe_serialize(data)
            logger.debug(
                _("Full data payload: %s"),
                json.dumps(safe_data, indent=2, ensure_ascii=False),
            )
        except Exception as e:
            logger.debug(_("Failed to serialize data payload: %s"), e)

        key = data.get("key", {})

        if key.get("fromMe"):
            return None

        remote_jid: str = key.get("remoteJid", "")
        msg_id: str = key.get("id", "")

        if not remote_jid or not msg_id:
            return None

        # Skip group messages (@g.us)
        if "@g.us" in remote_jid:
            return None

        message = data.get("message", {})
        text: str = (
            message.get("conversation")
            or message.get("extendedTextMessage", {}).get("text", "")
            or message.get("imageMessage", {}).get("caption", "")
            or message.get("videoMessage", {}).get("caption", "")
            or message.get("documentMessage", {}).get("caption", "")
            or ""
        )

        sender_number = WhatsAppChannel._clean_number(remote_jid)
        # Evolution API includes the bot's own JID as "owner" in global events
        owner_jid: str = data.get("owner", "")
        # Fallback: if owner is not provided, use instance_id as receiver phone
        # (Evolution API instance names are often the phone number itself)
        receiver_number = (
            WhatsAppChannel._clean_number(owner_jid) if owner_jid else instance_id
        )

        logger.debug(
            _("Parsed phone numbers - remote_jid=%s -> sender=%s, owner_jid=%s, instance_id=%s -> receiver=%s"),
            remote_jid,
            sender_number,
            owner_jid,
            instance_id,
            receiver_number,
        )

        # Capture for closure — use instance_id from payload, not a fixed value
        _instance = instance_id
        _channel = self._channel

        async def _callback(reply: str) -> None:
            await _channel.send_text(_instance, sender_number, reply)

        return IncomingMessage(
            id=msg_id,
            channel=ChannelType.whatsapp,
            instance_id=instance_id,
            sender_id=sender_number,
            receiver_id=receiver_number,
            text=text,
            received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            callback=_callback,
        )
