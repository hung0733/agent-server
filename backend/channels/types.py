from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MediaType = Literal["image", "video", "audio", "document"]
InboundContentType = Literal["text", "interactive", "image", "video", "audio", "document", "unknown"]


class ChannelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class WhatsAppInboundMessage(ChannelModel):
    event: str
    instance: str | None = None
    data: Any
    raw: dict[str, Any]


class ReceivedMessage(ChannelModel):
    instance: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    remote_jid: str | None = None
    phone_no: str | None = None
    content: str | None = None
    content_type: InboundContentType = "unknown"
    message_id: str | None = None
    has_text: bool = False
    has_media: bool = False
    media_url: str | None = None
    media_mimetype: str | None = None
    media_caption: str | None = None
    file_name: str | None = None
    quoted_message_id: str | None = None
    raw: dict[str, Any]
