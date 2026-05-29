import base64

import pytest

from backend.channels import EvolutionWhatsAppChannel
from backend.channels import evolution_handler
from backend.channels.evolution_handler import (
    build_msg_queue_task,
    extract_message_metadata,
    log_inbound_message,
    log_received_message,
)
from backend.channels.types import WhatsAppInboundMessage
from backend.llm.types import StreamChunk


class FakeQueue:
    def __init__(self):
        self.tasks = []

    async def enqueue(self, task):
        self.tasks.append(task)


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
async def test_log_inbound_message_enqueues_text_task(monkeypatch):
    queue = FakeQueue()

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
    )

    assert len(queue.tasks) == 1
    assert queue.tasks[0].agent_id == "agent-123"
    assert queue.tasks[0].session_id == "default-123"
    assert queue.tasks[0].message == "hello"
    assert queue.tasks[0].files is None


@pytest.mark.asyncio
async def test_build_msg_queue_task_includes_media_file_bytes():
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

    task = await build_msg_queue_task(received_message)

    assert task is not None
    assert task.agent_id == "agent-123"
    assert task.session_id == "default-123"
    assert task.message == "see image"
    assert task.files == [
        {
            "mimetype": "image/jpeg",
            "filename": "pic.jpg",
            "bytes": raw_bytes,
        }
    ]


@pytest.mark.asyncio
async def test_missing_agent_or_session_does_not_enqueue(monkeypatch):
    queue = FakeQueue()
    warnings = []

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
    )

    assert queue.tasks == []
    assert warnings


@pytest.mark.asyncio
async def test_log_inbound_message_task_callback_sends_agent_response_on_text_end(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="content", content="你好"))
            assert sent_messages == []
            await task.callback(StreamChunk(chunk_type="text_end"))
            await task.callback(StreamChunk(chunk_type="done"))

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
    )

    assert sent_messages == [("85298765432", "你好", {})]


@pytest.mark.asyncio
async def test_log_inbound_message_done_fallback_sends_unsent_response(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="content", content="fallback"))
            await task.callback(StreamChunk(chunk_type="done"))

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
    )

    assert sent_messages == [("85298765432", "fallback", {})]


@pytest.mark.asyncio
async def test_log_inbound_message_task_callback_sends_tool_summary_as_separate_reply(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="tool", content="search"))
            await task.callback(StreamChunk(chunk_type="tool", content="memory"))
            await task.callback(StreamChunk(chunk_type="content", content="完成"))
            await task.callback(StreamChunk(chunk_type="text_end"))
            await task.callback(StreamChunk(chunk_type="done"))

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
    )

    assert sent_messages == [
        ("85298765432", "🔧 已調用工具：search\n🔧 已調用工具：memory\n", {}),
        ("85298765432", "完成", {}),
    ]


@pytest.mark.asyncio
async def test_log_inbound_message_done_fallback_sends_tool_summary_without_response_text(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="tool", content="search"))
            await task.callback(StreamChunk(chunk_type="done"))

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
    )

    assert sent_messages == [
        ("85298765432", "🔧 已調用工具：search\n", {}),
    ]


@pytest.mark.asyncio
async def test_log_inbound_message_replies_with_inbound_instance(monkeypatch):
    posts = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="content", content="pong"))
            await task.callback(StreamChunk(chunk_type="text_end"))
            await task.callback(StreamChunk(chunk_type="done"))

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
    )

    assert posts == [
        {
            "url": "http://evolution.test/message/sendText/Moss",
            "headers": {"apikey": "global-key"},
            "json": {"number": "85298765432", "text": "pong"},
        }
    ]
