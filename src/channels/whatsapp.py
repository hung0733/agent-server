"""WhatsApp channel via Evolution API.

Two components:
  - WhatsAppChannel   : outbound REST sender (POST /message/sendText)
  - WhatsAppWSClient  : inbound WebSocket listener, enqueues IncomingMessage
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import aiohttp

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
        raise RuntimeError(f"Required environment variable '{name}' is not set")
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
            text:         Message body.
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
    """Connects to Evolution API WebSocket and enqueues incoming messages.

    Reconnects automatically with exponential backoff on disconnect.
    Duplicate messages are filtered via MessageDeduplicator.
    """

    def __init__(
        self,
        instance_name: str,
        queue: "QueueManager",
        channel: WhatsAppChannel,
        dedup: MessageDeduplicator,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._instance = instance_name
        self._queue = queue
        self._channel = channel
        self._dedup = dedup
        self._api_url = (api_url or _require_env("EVOLUTION_API_URL")).rstrip("/")
        self._api_key = api_key or _require_env("EVOLUTION_API_KEY")
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Spawn the WebSocket listener as a background task."""
        self._task = asyncio.create_task(
            self._listen_loop(), name=f"ws-whatsapp-{self._instance}"
        )

    async def stop(self) -> None:
        """Cancel the background listener task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(_("WhatsAppWSClient stopped (instance=%s)"), self._instance)

    async def _listen_loop(self) -> None:
        """Outer loop: reconnects on failure with exponential backoff."""
        attempt = 0
        while True:
            try:
                await self._connect_and_receive()
                attempt = 0  # reset on clean disconnect
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = _WS_RECONNECT_DELAYS[
                    min(attempt, len(_WS_RECONNECT_DELAYS) - 1)
                ]
                logger.warning(
                    _("WS disconnected (instance=%s, attempt=%d): %s — retrying in %ds"),
                    self._instance,
                    attempt + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    async def _connect_and_receive(self) -> None:
        """Open one WebSocket connection and receive events until it closes."""
        # Evolution API WebSocket URL
        ws_url = (
            self._api_url.replace("http://", "ws://").replace("https://", "wss://")
            + f"/ws?apikey={self._api_key}&instanceName={self._instance}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, heartbeat=30) as ws:
                logger.info(
                    _("WS connected to Evolution API (instance=%s)"), self._instance
                )
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_raw(msg.json())
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        raise RuntimeError(f"WS error: {ws.exception()}")
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        logger.info(
                            _("WS closed by server (instance=%s)"), self._instance
                        )
                        break

    async def _handle_raw(self, payload: dict) -> None:
        """Parse a raw WS payload and enqueue if it's a valid inbound message."""
        msg = self._parse_event(payload)
        if msg is None:
            return
        if await self._dedup.is_duplicate(msg.id):
            logger.debug(_("Duplicate message dropped: %s"), msg.id)
            return
        await self._dedup.register(msg.id)
        # Map IncomingMessage → QueueTask.
        # agent_id is read from env; session_id is the sender's phone number.
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
            _("Queued message from %s (id=%s)"),
            msg.sender_id,
            msg.id,
        )

    def _parse_event(self, payload: dict) -> Optional[IncomingMessage]:
        """Parse an Evolution API event payload into an IncomingMessage.

        Returns None for events we don't handle (non-message events,
        outbound messages, group messages, etc.).
        """
        event = payload.get("event") or payload.get("type") or ""
        if event not in ("messages.upsert", "MESSAGES_UPSERT"):
            return None

        data = payload.get("data", {})
        key = data.get("key", {})

        # Drop messages sent by the bot itself
        if key.get("fromMe"):
            return None

        remote_jid: str = key.get("remoteJid", "")
        msg_id: str = key.get("id", "")

        if not remote_jid or not msg_id:
            return None

        # Extract text (conversation > extendedTextMessage > caption)
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

        # Capture for closure
        instance = self._instance
        channel = self._channel

        async def _callback(reply: str) -> None:
            await channel.send_text(instance, sender_number, reply)

        return IncomingMessage(
            id=msg_id,
            channel=ChannelType.whatsapp,
            instance_id=self._instance,
            sender_id=sender_number,
            text=text,
            received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            callback=_callback,
        )
