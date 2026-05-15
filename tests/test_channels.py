import asyncio
from collections.abc import Callable

import pytest

from backend.channels import (
    CommunicationChannel,
    EvolutionWhatsAppChannel,
    InteractiveButton,
    InteractiveListRow,
    InteractiveListSection,
)
from backend.channels.evolution_whatsapp import MessageDeduper


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {"ok": True}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self):
        self.posts = []
        self.closed = False

    async def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return FakeResponse({"url": url, "json": json})

    async def aclose(self):
        self.closed = True


class FakeSocketClient:
    def __init__(self):
        self.handlers = {}
        self.connected = None
        self.disconnected = False

    def on(self, event, handler=None, namespace=None):
        self.handlers[(namespace, event)] = handler

    async def connect(self, url, namespaces=None):
        self.connected = {"url": url, "namespaces": namespaces}

    async def disconnect(self):
        self.disconnected = True

    async def emit_inbound(self, payload):
        await self.handlers[("/", "messages.upsert")](payload)


def make_channel(http_client=None, socket_factory: Callable[[], FakeSocketClient] | None = None):
    return EvolutionWhatsAppChannel(
        whatsapp_instance="agent-instance",
        whatsapp_key="instance-key",
        api_url="http://evolution.test",
        global_api_key="global-key",
        http_client=http_client or FakeHttpClient(),
        socketio_client_factory=socket_factory,
    )


def inbound(data, instance="sales-agent"):
    return {
        "event": "messages.upsert",
        "instance": instance,
        "data": data,
    }


def test_communication_channel_is_abstract():
    with pytest.raises(TypeError):
        CommunicationChannel()


@pytest.mark.asyncio
async def test_send_methods_use_instance_key_and_instance_endpoints():
    http_client = FakeHttpClient()
    channel = make_channel(http_client=http_client)

    await channel.send_text("85298765432", "hello", delay=1000, link_preview=False)
    await channel.send_media("85298765432", "image", "base64", caption="cap", file_name="pic.jpg")
    await channel.send_interactive_buttons(
        "85298765432",
        "Approve?",
        [
            InteractiveButton(id="approve", display_text="Approve"),
            InteractiveButton(id="reject", display_text="Reject"),
        ],
        description="Choose one",
    )
    await channel.send_interactive_list(
        "85298765432",
        "Choose item",
        "Open",
        "Footer",
        [
            InteractiveListSection(
                title="Actions",
                rows=[InteractiveListRow(title="Approve", row_id="approve", description="Approve request")],
            )
        ],
    )
    await channel.mark_message_as_read("85298765432", "msg-1")

    assert [post["url"] for post in http_client.posts] == [
        "http://evolution.test/message/sendText/agent-instance",
        "http://evolution.test/message/sendMedia/agent-instance",
        "http://evolution.test/message/sendButtons/agent-instance",
        "http://evolution.test/message/sendList/agent-instance",
        "http://evolution.test/chat/markMessageAsRead/agent-instance",
    ]
    assert all(post["headers"] == {"apikey": "instance-key"} for post in http_client.posts)
    assert http_client.posts[0]["json"] == {
        "number": "85298765432",
        "text": "hello",
        "delay": 1000,
        "linkPreview": False,
    }
    assert http_client.posts[1]["json"]["fileName"] == "pic.jpg"
    assert http_client.posts[2]["json"]["buttons"][0] == {
        "type": "reply",
        "displayText": "Approve",
        "id": "approve",
    }
    assert http_client.posts[3]["json"]["sections"][0]["rows"][0]["rowId"] == "approve"
    assert http_client.posts[4]["json"] == {"number": "85298765432", "messageId": "msg-1"}


@pytest.mark.asyncio
async def test_send_media_rejects_invalid_media_type():
    channel = make_channel()

    with pytest.raises(ValueError):
        await channel.send_media("85298765432", "sticker", "base64")


@pytest.mark.asyncio
async def test_websocket_setup_only_enables_messages_upsert():
    http_client = FakeHttpClient()
    channel = make_channel(http_client=http_client)

    await channel.ensure_message_listener_enabled()

    assert http_client.posts == [
        {
            "url": "http://evolution.test/websocket/set/agent-instance",
            "headers": {"apikey": "instance-key"},
            "json": {"websocket": {"enabled": True, "events": ["MESSAGES_UPSERT"]}},
        }
    ]


@pytest.mark.asyncio
async def test_listen_messages_uses_global_root_namespace_and_keeps_instance():
    socket = FakeSocketClient()
    channel = make_channel(socket_factory=lambda: socket)
    listener = channel.listen_messages()

    first = asyncio.create_task(anext(listener))
    await asyncio.sleep(0)
    assert socket.connected == {
        "url": "http://evolution.test?apikey=global-key",
        "namespaces": ["/"],
    }

    await socket.emit_inbound(
        {
            "event": "messages.upsert",
            "instance": "sales-agent",
            "data": {"key": {"remoteJid": "85298765432@s.whatsapp.net", "id": "msg-1"}},
        }
    )

    message = await first
    assert message.instance == "sales-agent"
    assert message.raw["instance"] == "sales-agent"

    await listener.aclose()
    assert socket.disconnected is True


def test_deduper_filters_same_key_within_five_seconds():
    deduper = MessageDeduper(ttl_seconds=5)

    assert deduper.is_duplicate("instance:jid:msg-1", now=100) is False
    assert deduper.is_duplicate("instance:jid:msg-1", now=104.9) is True
    assert deduper.is_duplicate("instance:jid:msg-1", now=105.1) is False


def test_to_received_message_extracts_text_and_phone_no():
    channel = make_channel()
    raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {"conversation": "hello"},
        }
    )

    message = channel.to_received_message(channel._inbound_message(raw))

    assert message.instance == "sales-agent"
    assert message.remote_jid == "85297548257@s.whatsapp.net"
    assert message.phone_no == "85297548257"
    assert message.content_type == "text"
    assert message.content == "hello"
    assert message.has_text is True
    assert message.has_media is False


def test_to_received_message_extracts_extended_text():
    channel = make_channel()
    raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {"extendedTextMessage": {"text": "extended hello"}},
        }
    )

    message = channel.to_received_message(channel._inbound_message(raw))

    assert message.content_type == "text"
    assert message.content == "extended hello"


def test_to_received_message_extracts_interactive_buttons_and_list():
    channel = make_channel()
    button_raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {"buttonsResponseMessage": {"selectedButtonId": "approve"}},
        }
    )
    list_raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-2"},
            "message": {"listResponseMessage": {"singleSelectReply": {"selectedRowId": "row-1"}}},
        }
    )

    button_message = channel.to_received_message(channel._inbound_message(button_raw))
    list_message = channel.to_received_message(channel._inbound_message(list_raw))

    assert button_message.content_type == "interactive"
    assert button_message.content == "approve"
    assert list_message.content_type == "interactive"
    assert list_message.content == "row-1"


def test_to_received_message_extracts_image_with_caption():
    channel = make_channel()
    raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {
                "imageMessage": {
                    "caption": "see image",
                    "mimetype": "image/jpeg",
                    "url": "https://media.test/image.jpg",
                }
            },
        }
    )

    message = channel.to_received_message(channel._inbound_message(raw))

    assert message.content_type == "image"
    assert message.content == "see image"
    assert message.media_caption == "see image"
    assert message.media_mimetype == "image/jpeg"
    assert message.media_url == "https://media.test/image.jpg"
    assert message.has_text is True
    assert message.has_media is True


def test_to_received_message_extracts_document_with_caption_and_file_name():
    channel = make_channel()
    raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {
                "documentMessage": {
                    "caption": "please review",
                    "fileName": "report.pdf",
                    "mimetype": "application/pdf",
                    "url": "https://media.test/report.pdf",
                }
            },
        }
    )

    message = channel.to_received_message(channel._inbound_message(raw))

    assert message.content_type == "document"
    assert message.content == "please review"
    assert message.file_name == "report.pdf"
    assert message.media_caption == "please review"
    assert message.has_text is True
    assert message.has_media is True


def test_to_received_message_extracts_audio_and_video_metadata():
    channel = make_channel()
    audio_raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {"audioMessage": {"mimetype": "audio/ogg", "url": "https://media.test/audio.ogg"}},
        }
    )
    video_raw = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-2"},
            "message": {"videoMessage": {"caption": "clip", "mimetype": "video/mp4", "url": "https://media.test/v.mp4"}},
        }
    )

    audio_message = channel.to_received_message(channel._inbound_message(audio_raw))
    video_message = channel.to_received_message(channel._inbound_message(video_raw))

    assert audio_message.content_type == "audio"
    assert audio_message.has_media is True
    assert audio_message.has_text is False
    assert audio_message.media_mimetype == "audio/ogg"
    assert video_message.content_type == "video"
    assert video_message.content == "clip"
    assert video_message.has_text is True


@pytest.mark.asyncio
async def test_receive_message_handler_is_called_after_dedupe():
    socket = FakeSocketClient()
    calls = []

    async def handler(remote_jid, instance, content):
        calls.append((remote_jid, instance, content))

    channel = EvolutionWhatsAppChannel(
        whatsapp_instance="agent-instance",
        whatsapp_key="instance-key",
        api_url="http://evolution.test",
        global_api_key="global-key",
        http_client=FakeHttpClient(),
        socketio_client_factory=lambda: socket,
        receive_message_handler=handler,
    )
    listener = channel.listen_messages()
    first = asyncio.create_task(anext(listener))
    await asyncio.sleep(0)
    payload = inbound(
        {
            "key": {"remoteJid": "85297548257@s.whatsapp.net", "id": "msg-1"},
            "message": {"conversation": "hello"},
        }
    )

    await socket.emit_inbound(payload)
    await socket.emit_inbound(payload)
    message = await first

    assert message.instance == "sales-agent"
    assert calls == [("85297548257@s.whatsapp.net", "sales-agent", "hello")]

    await listener.aclose()
