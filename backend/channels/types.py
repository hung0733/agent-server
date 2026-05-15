from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MediaType = Literal["image", "video", "audio", "document"]
InboundContentType = Literal["text", "interactive", "image", "video", "audio", "document", "unknown"]


class ChannelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class InteractiveButton(ChannelModel):
    button_type: Literal["reply", "copy", "url", "call", "pix"] = Field(default="reply", alias="type")
    display_text: str | None = Field(default=None, alias="displayText")
    id: str | None = None
    url: str | None = None
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    copy_code: str | None = Field(default=None, alias="copyCode")
    currency: str | None = None
    name: str | None = None
    key_type: str | None = Field(default=None, alias="keyType")
    key: str | None = None


class InteractiveListRow(ChannelModel):
    title: str
    row_id: str = Field(alias="rowId")
    description: str | None = None


class InteractiveListSection(ChannelModel):
    title: str
    rows: list[InteractiveListRow]


class WhatsAppInboundMessage(ChannelModel):
    event: str
    instance: str | None = None
    data: Any
    raw: dict[str, Any]


class ReceivedMessage(ChannelModel):
    instance: str | None = None
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
    raw: dict[str, Any]
