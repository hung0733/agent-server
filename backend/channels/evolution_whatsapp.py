from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from os import getenv
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from backend.channels.base import CommunicationChannel
from backend.channels.types import (
    InteractiveButton,
    InteractiveListSection,
    MediaType,
    ReceivedMessage,
    WhatsAppInboundMessage,
)
from backend.i18n import t


load_dotenv()

logger = logging.getLogger(__name__)

ReceiveMessageHandler = Callable[[str | None, str | None, str | None], Awaitable[None] | None]


class MessageDeduper:
    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}

    def is_duplicate(self, key: str, now: float | None = None) -> bool:
        now = monotonic() if now is None else now
        self._purge(now)
        expires_at = self._seen.get(key)
        if expires_at and expires_at > now:
            return True
        self._seen[key] = now + self.ttl_seconds
        return False

    def _purge(self, now: float) -> None:
        expired = [key for key, expires_at in self._seen.items() if expires_at <= now]
        for key in expired:
            del self._seen[key]


class EvolutionWhatsAppChannel(CommunicationChannel):
    def __init__(
        self,
        whatsapp_instance: str | None = None,
        whatsapp_key: str | None = None,
        *,
        api_url: str | None = None,
        global_api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        socketio_client_factory: Callable[[], Any] | None = None,
        deduper: MessageDeduper | None = None,
        receive_message_handler: ReceiveMessageHandler | None = None,
    ) -> None:
        self.whatsapp_instance = whatsapp_instance
        self.whatsapp_key = whatsapp_key
        self.api_url = (api_url or getenv("EVOLUTION_API_URL", "")).rstrip("/")
        self.global_api_key = global_api_key or getenv("EVOLUTION_API_KEY")
        self._http_client = http_client or httpx.AsyncClient(timeout=30)
        self._owns_http_client = http_client is None
        self._socketio_client_factory = socketio_client_factory
        self._deduper = deduper or MessageDeduper(ttl_seconds=5)
        self._receive_message_handler = receive_message_handler

    async def send_text(self, number: str, text: str, **options: Any) -> dict[str, Any]:
        payload = {"number": number, "text": text, **self._compact_options(options)}
        return await self._post_instance("message/sendText", payload)

    async def send_media(
        self,
        number: str,
        mediatype: MediaType,
        media: str,
        **options: Any,
    ) -> dict[str, Any]:
        if mediatype not in {"image", "video", "audio", "document"}:
            raise ValueError(t("channels.evolution.invalid_media_type"))
        payload = {"number": number, "mediatype": mediatype, "media": media, **self._compact_options(options)}
        return await self._post_instance("message/sendMedia", payload)

    async def send_image(self, number: str, media: str, **options: Any) -> dict[str, Any]:
        return await self.send_media(number, "image", media, **options)

    async def send_video(self, number: str, media: str, **options: Any) -> dict[str, Any]:
        return await self.send_media(number, "video", media, **options)

    async def send_audio(self, number: str, media: str, **options: Any) -> dict[str, Any]:
        return await self.send_media(number, "audio", media, **options)

    async def send_document(self, number: str, media: str, **options: Any) -> dict[str, Any]:
        return await self.send_media(number, "document", media, **options)

    async def send_interactive_buttons(
        self,
        number: str,
        title: str,
        buttons: Sequence[InteractiveButton],
        **options: Any,
    ) -> dict[str, Any]:
        payload = {
            "number": number,
            "title": title,
            "buttons": [self._model_dump(button) for button in buttons],
            **self._compact_options(options),
        }
        return await self._post_instance("message/sendButtons", payload)

    async def send_interactive_list(
        self,
        number: str,
        title: str,
        button_text: str,
        footer_text: str,
        sections: Sequence[InteractiveListSection],
        **options: Any,
    ) -> dict[str, Any]:
        payload = {
            "number": number,
            "title": title,
            "buttonText": button_text,
            "footerText": footer_text,
            "sections": [self._model_dump(section) for section in sections],
            **self._compact_options(options),
        }
        return await self._post_instance("message/sendList", payload)

    async def mark_message_as_read(self, number: str, message_id: str) -> dict[str, Any]:
        return await self._post_instance("chat/markMessageAsRead", {"number": number, "messageId": message_id})

    async def ensure_message_listener_enabled(self) -> dict[str, Any]:
        payload = {"websocket": {"enabled": True, "events": ["MESSAGES_UPSERT"]}}
        return await self._post_instance("websocket/set", payload)

    async def _post_instance(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.whatsapp_instance:
            raise ValueError(t("channels.evolution.missing_whatsapp_instance"))
        if not self.whatsapp_key:
            raise ValueError(t("channels.evolution.missing_whatsapp_key"))

        response = await self._http_client.post(
            f"{self.api_url}/{path}/{self.whatsapp_instance}",
            headers={"apikey": self.whatsapp_key},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def listen_messages(self) -> AsyncIterator[WhatsAppInboundMessage]:
        return self._listen_messages()

    async def _listen_messages(self) -> AsyncIterator[WhatsAppInboundMessage]:
        socket = self._create_socketio_client()
        queue: asyncio.Queue[WhatsAppInboundMessage] = asyncio.Queue()

        async def on_messages_upsert(payload: dict[str, Any]) -> None:
            message = self._inbound_message(payload)
            if self._deduper.is_duplicate(self._dedupe_key(message)):
                logger.info(t("channels.evolution.duplicate_message_skipped"))
                return
            await self.handle_received_message(message)
            await queue.put(message)

        socket.on("messages.upsert", handler=on_messages_upsert, namespace="/")
        await socket.connect(
            f"{self.api_url}?apikey={quote(self._global_listen_api_key())}",
            namespaces=["/"],
        )

        try:
            while True:
                yield await queue.get()
        finally:
            await socket.disconnect()

    def _create_socketio_client(self) -> Any:
        if self._socketio_client_factory:
            return self._socketio_client_factory()

        import socketio

        return socketio.AsyncClient()

    def _global_listen_api_key(self) -> str:
        api_key = self.global_api_key or self.whatsapp_key
        if not api_key:
            raise ValueError(t("channels.evolution.missing_global_api_key"))
        return api_key

    def _inbound_message(self, payload: dict[str, Any]) -> WhatsAppInboundMessage:
        return WhatsAppInboundMessage(
            event=str(payload.get("event") or "messages.upsert"),
            instance=payload.get("instance"),
            data=payload.get("data"),
            raw=payload,
        )

    async def handle_received_message(self, message: WhatsAppInboundMessage) -> ReceivedMessage:
        received_message = self.to_received_message(message)
        if self._receive_message_handler:
            try:
                result = self._receive_message_handler(
                    received_message.remote_jid,
                    received_message.instance,
                    received_message.content,
                )
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(t("channels.evolution.receive_handler_failed"))
                raise
        return received_message

    def to_received_message(self, message: WhatsAppInboundMessage) -> ReceivedMessage:
        data = message.data if isinstance(message.data, dict) else {}
        key = data.get("key") if isinstance(data.get("key"), dict) else {}
        remote_jid = self._extract_remote_jid(message)
        message_id = key.get("id") or data.get("messageId")
        text_content = self._extract_text_content(data)
        interactive_content = self._extract_interactive_content(data)
        media_content = self._extract_media_content(data)

        if media_content:
            content_type = media_content["content_type"]
            media_caption = media_content.get("media_caption")
            file_name = media_content.get("file_name")
            media_url = media_content.get("media_url")
            content = media_caption or file_name or media_url
            has_media = True
            has_text = bool(media_caption)
        elif interactive_content:
            content_type = "interactive"
            content = interactive_content
            media_caption = None
            file_name = None
            media_url = None
            has_media = False
            has_text = True
        elif text_content:
            content_type = "text"
            content = text_content
            media_caption = None
            file_name = None
            media_url = None
            has_media = False
            has_text = True
        else:
            content_type = "unknown"
            content = None
            media_caption = None
            file_name = None
            media_url = None
            has_media = False
            has_text = False

        return ReceivedMessage(
            instance=message.instance,
            remote_jid=remote_jid,
            phone_no=self._extract_phone_no(remote_jid),
            content=content,
            content_type=content_type,
            message_id=message_id,
            has_text=has_text,
            has_media=has_media,
            media_url=media_url,
            media_mimetype=media_content.get("media_mimetype") if media_content else None,
            media_caption=media_caption,
            file_name=file_name,
            raw=message.raw,
        )

    def _extract_remote_jid(self, message: WhatsAppInboundMessage) -> str | None:
        data = message.data if isinstance(message.data, dict) else {}
        key = data.get("key") if isinstance(data.get("key"), dict) else {}
        return key.get("remoteJid") or data.get("remoteJid") or message.raw.get("sender")

    def _extract_phone_no(self, remote_jid: str | None) -> str | None:
        if not remote_jid:
            return None
        phone_part = remote_jid.split("@", 1)[0]
        phone_no = re.sub(r"\D", "", phone_part)
        return phone_no or None

    def _extract_text_content(self, data: dict[str, Any]) -> str | None:
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        extended_text = message.get("extendedTextMessage")
        if isinstance(extended_text, dict) and extended_text.get("text"):
            return extended_text["text"]
        if message.get("conversation"):
            return message["conversation"]
        return data.get("text") or data.get("body")

    def _extract_interactive_content(self, data: dict[str, Any]) -> str | None:
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        button = message.get("buttonsResponseMessage")
        if isinstance(button, dict):
            return button.get("selectedButtonId") or button.get("selectedDisplayText")

        list_response = message.get("listResponseMessage")
        if isinstance(list_response, dict):
            single_select = list_response.get("singleSelectReply")
            if isinstance(single_select, dict) and single_select.get("selectedRowId"):
                return single_select["selectedRowId"]
            title = list_response.get("title")
            if isinstance(title, str):
                return title

        interactive = message.get("interactiveResponseMessage")
        if isinstance(interactive, dict):
            native = interactive.get("nativeFlowResponseMessage")
            if isinstance(native, dict):
                return native.get("name") or native.get("buttonParamsJson")

        return None

    def _extract_media_content(self, data: dict[str, Any]) -> dict[str, str | None] | None:
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        for content_type, key in (
            ("image", "imageMessage"),
            ("video", "videoMessage"),
            ("audio", "audioMessage"),
            ("document", "documentMessage"),
        ):
            media = message.get(key)
            if not isinstance(media, dict):
                continue
            media_url = media.get("url") or media.get("mediaUrl") or media.get("media") or media.get("base64")
            return {
                "content_type": content_type,
                "media_url": media_url,
                "media_mimetype": media.get("mimetype"),
                "media_caption": media.get("caption"),
                "file_name": media.get("fileName"),
            }
        return None

    def _dedupe_key(self, message: WhatsAppInboundMessage) -> str:
        data = message.data if isinstance(message.data, dict) else {}
        key = data.get("key") if isinstance(data.get("key"), dict) else {}
        message_id = key.get("id")
        remote_jid = key.get("remoteJid") or data.get("remoteJid") or message.raw.get("sender")

        if message_id:
            return f"{message.instance}:{remote_jid}:{message_id}"

        text = (
            data.get("message", {}).get("conversation")
            if isinstance(data.get("message"), dict)
            else data.get("text") or data.get("body") or ""
        )
        timestamp_bucket = int(monotonic() // self._deduper.ttl_seconds)
        return f"{message.instance}:{remote_jid}:{str(text).strip()}:{timestamp_bucket}"

    def _compact_options(self, options: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "file_name": "fileName",
            "link_preview": "linkPreview",
            "footer_text": "footerText",
            "button_text": "buttonText",
        }
        return {aliases.get(key, key): value for key, value in options.items() if value is not None}

    def _model_dump(self, model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump(by_alias=True, exclude_none=True)
        return dict(model)

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()
