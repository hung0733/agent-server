import base64

import pytest

from backend.channels import EvolutionWhatsAppChannel
from backend.channels import evolution_handler
from backend.channels.evolution_handler import (
    build_llm_message_payload,
    extract_message_metadata,
    log_inbound_message,
    log_received_message,
)
from backend.channels.types import WhatsAppInboundMessage
from backend.llm.types import StreamChunk


class FakeQueue:
    def __init__(self):
        self.payloads = []

    async def create_msg_queue(self, payload):
        self.payloads.append(payload)
        yield StreamChunk(chunk_type="done")


def inbound(data, instance="sales-agent"):
    return WhatsAppInboundMessage(
        event="messages.upsert",
        instance=instance,
        data=data,
        raw={"instance": instance},
    )


def test_extract_message_metadata_from_whatsapp_payload():
    message = inbound({"key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"}})

    assert extract_message_metadata(message) == ("msg-1", "85298765432@s.whatsapp.net")


def test_log_received_message_includes_content_metadata(monkeypatch):
    calls = []
    monkeypatch.setattr(evolution_handler.logger, "info", lambda *args: calls.append(args))
    received_message = EvolutionWhatsAppChannel().to_received_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"imageMessage": {"caption": "image text"}},
            }
        )
    )

    log_received_message(received_message)

    assert calls[0][1:] == (
        "sales-agent",
        None,
        None,
        "msg-1",
        "85298765432@s.whatsapp.net",
        "85298765432",
        "image",
        True,
        True,
    )


@pytest.mark.asyncio
async def test_log_inbound_message_enqueues_text_payload(monkeypatch):
    queue = FakeQueue()
    stream_tasks = set()

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    monkeypatch.setattr(evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session)

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hello"},
            }
        ),
        queue,
        stream_tasks=stream_tasks,
    )

    for task in tuple(stream_tasks):
        await task

    assert queue.payloads == [
        {
            "agent_id": "agent-123",
            "session_id": "default-123",
            "message": "hello",
            "files": None,
        }
    ]


@pytest.mark.asyncio
async def test_build_llm_message_payload_includes_media_file_bytes():
    raw_bytes = b"image-bytes"
    received_message = EvolutionWhatsAppChannel().to_received_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {
                    "imageMessage": {
                        "caption": "see image",
                        "mimetype": "image/jpeg",
                        "fileName": "pic.jpg",
                        "base64": base64.b64encode(raw_bytes).decode(),
                    }
                },
            }
        )
    )
    received_message.agent_id = "agent-123"
    received_message.session_id = "default-123"

    payload = await build_llm_message_payload(received_message)

    assert payload == {
        "agent_id": "agent-123",
        "session_id": "default-123",
        "message": "see image",
        "files": [
            {
                "mimetype": "image/jpeg",
                "filename": "pic.jpg",
                "bytes": raw_bytes,
            }
        ],
    }


@pytest.mark.asyncio
async def test_missing_agent_or_session_does_not_enqueue(monkeypatch):
    queue = FakeQueue()
    warnings = []
    stream_tasks = set()

    async def resolve_agent_session(message):
        return "agent-123", None

    monkeypatch.setattr(evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session)
    monkeypatch.setattr(evolution_handler.logger, "warning", lambda *args: warnings.append(args))

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hello"},
            }
        ),
        queue,
        stream_tasks=stream_tasks,
    )

    assert queue.payloads == []
    assert warnings


@pytest.mark.asyncio
async def test_log_inbound_message_sends_agent_response_to_whatsapp(monkeypatch):
    stream_tasks = set()
    sent_messages = []

    class ResponseQueue:
        async def create_msg_queue(self, payload):
            yield StreamChunk(chunk_type="content", content="你")
            yield StreamChunk(chunk_type="content", content="好")
            yield StreamChunk(chunk_type="done")

    class FakeChannel:
        async def send_text(self, number, text, **options):
            sent_messages.append((number, text, options))
            return {"ok": True}

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    monkeypatch.setattr(evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session)

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hi"},
            }
        ),
        ResponseQueue(),
        channel=FakeChannel(),
        stream_tasks=stream_tasks,
    )

    for task in tuple(stream_tasks):
        await task

    assert sent_messages == [("85298765432", "你好", {})]


@pytest.mark.asyncio
async def test_log_inbound_message_replies_with_inbound_instance(monkeypatch):
    stream_tasks = set()
    posts = []

    class ResponseQueue:
        async def create_msg_queue(self, payload):
            yield StreamChunk(chunk_type="content", content="pong")
            yield StreamChunk(chunk_type="done")

    class FakeHttpClient:
        async def post(self, url, headers=None, json=None):
            posts.append({"url": url, "headers": headers, "json": json})

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"ok": True}

            return Response()

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    monkeypatch.setattr(evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session)
    channel = EvolutionWhatsAppChannel(
        api_url="http://evolution.test",
        global_api_key="global-key",
        http_client=FakeHttpClient(),
    )

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "ping"},
            },
            instance="Moss",
        ),
        ResponseQueue(),
        channel=channel,
        stream_tasks=stream_tasks,
    )

    for task in tuple(stream_tasks):
        await task

    assert posts == [
        {
            "url": "http://evolution.test/message/sendText/Moss",
            "headers": {"apikey": "global-key"},
            "json": {"number": "85298765432", "text": "pong"},
        }
    ]
