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
from typing import TYPE_CHECKING, Optional

import aiohttp
import socketio

from channels.base import AbstractChannel, ChannelType, IncomingMessage
from i18n import _

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

    async def send_text(
        self, instance_id: str, recipient_id: str, text: str
    ) -> None:
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
                        _("Sent message to %s via instance %s"), recipient_id, instance_id
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
        """Cancel the background listener task."""
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
        @sio.on("messages.upsert")
        async def on_messages_upsert(data: dict) -> None:
            await self._handle_raw("messages.upsert", data)

        @sio.on("MESSAGES_UPSERT")
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

        agent_id = os.getenv("DEFAULT_AGENT_ID", "default")
        await self._queue.enqueue(
            agent_id=agent_id,
            session_id=msg.sender_id,
            message=msg.text,
            metadata={
                "channel": msg.channel,
                "instance_id": msg.instance_id,
                "msg_id": msg.id,
                "callback": msg.callback,
            },
        )
        logger.info(
            _("Queued message from %s via instance %s (id=%s)"),
            msg.sender_id,
            msg.instance_id,
            msg.id,
        )

    def _parse_message(
        self, event: str, instance_id: str, data: dict
    ) -> Optional[IncomingMessage]:
        """Parse event data into an IncomingMessage.

        Returns None for outbound messages, group messages, or non-text events.
        """
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
            text=text,
            received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            callback=_callback,
        )
