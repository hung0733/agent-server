import base64

import pytest

from backend.channels import EvolutionWhatsAppChannel
from backend.channels import evolution_handler
from backend.channels.evolution_handler import (
    WhatsAppMsgQueueTask,
    build_msg_queue_task,
    extract_message_metadata,
    log_inbound_message,
    log_received_message,
)
from backend.channels.types import WhatsAppInboundMessage
from backend.llm.types import StreamChunk


class FakeQueue:
    def __init__(self, resume_return=False):
        self.tasks = []
        self.resume_calls = []
        self.resume_return = resume_return

    async def resume_interrupt(self, agent_id, msg_id, task=None):
        self.resume_calls.append((agent_id, msg_id, task))
        return self.resume_return

    async def enqueue(self, task):
        self.tasks.append(task)


class FakeTask:
    agent_id = "agent-123"


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

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )

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
async def test_log_inbound_message_keeps_existing_quoted_message_id(monkeypatch):
    queue = FakeQueue()
    captured_messages = []
    fallback_calls = []
    info_calls = []

    class FakeChannel:
        async def find_message_quoted_message_id(self, message_id):
            fallback_calls.append(message_id)
            return "fallback-msg"

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    async def capture_task(message, **kwargs):
        captured_messages.append(message)
        return FakeTask()

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )
    monkeypatch.setattr(evolution_handler, "build_msg_queue_task", capture_task)
    monkeypatch.setattr(
        evolution_handler.logger, "info", lambda *args: info_calls.append(args)
    )

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {
                    "extendedTextMessage": {
                        "text": "approve",
                        "contextInfo": {"stanzaId": "quoted-msg-1"},
                    }
                },
            }
        ),
        queue,
        channel=FakeChannel(),
    )

    assert captured_messages[0].quoted_message_id == "quoted-msg-1"
    assert fallback_calls == []
    assert info_calls[0][1:] == (
        "sales-agent",
        "85298765432@s.whatsapp.net",
        "msg-1",
        "quoted-msg-1",
        "payload_context_info",
    )
    assert len(queue.tasks) == 1


@pytest.mark.asyncio
async def test_log_inbound_message_falls_back_to_stored_inbound_quoted_message_id(monkeypatch):
    queue = FakeQueue()
    captured_messages = []
    info_calls = []

    class FakeChannel:
        async def find_message_quoted_message_id(self, message_id):
            assert message_id == "msg-1"
            return "quoted-msg-1"

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    async def capture_task(message, **kwargs):
        captured_messages.append(message)
        return FakeTask()

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )
    monkeypatch.setattr(evolution_handler, "build_msg_queue_task", capture_task)
    monkeypatch.setattr(
        evolution_handler.logger, "info", lambda *args: info_calls.append(args)
    )

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hello"},
            }
        ),
        queue,
        channel=FakeChannel(),
    )

    assert captured_messages[0].quoted_message_id == "quoted-msg-1"
    assert info_calls[0][1:] == (
        "sales-agent",
        "85298765432@s.whatsapp.net",
        "msg-1",
        "quoted-msg-1",
        "evolution_find_message",
    )
    assert len(queue.tasks) == 1


@pytest.mark.asyncio
async def test_log_inbound_message_keeps_enqueue_when_quoted_fallback_empty(monkeypatch):
    queue = FakeQueue()
    captured_messages = []
    info_calls = []

    class FakeChannel:
        async def find_message_quoted_message_id(self, message_id):
            return None

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    async def capture_task(message, **kwargs):
        captured_messages.append(message)
        return FakeTask()

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )
    monkeypatch.setattr(evolution_handler, "build_msg_queue_task", capture_task)
    monkeypatch.setattr(
        evolution_handler.logger, "info", lambda *args: info_calls.append(args)
    )

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hello"},
            }
        ),
        queue,
        channel=FakeChannel(),
    )

    assert captured_messages[0].quoted_message_id is None
    assert info_calls[0][1:] == (
        "sales-agent",
        "85298765432@s.whatsapp.net",
        "msg-1",
        None,
        "none",
    )
    assert len(queue.tasks) == 1


@pytest.mark.asyncio
async def test_log_inbound_message_resumes_with_latest_outbound_message_id(monkeypatch):
    queue = FakeQueue(resume_return=True)
    captured_tasks = []

    class FakeChannel:
        async def find_message_quoted_message_id(self, message_id):
            return None

        async def find_latest_outbound_message_id(self, remote_jid):
            assert remote_jid == "85298765432@s.whatsapp.net"
            return "latest-outbound-msg"

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    async def capture_task(message, **kwargs):
        task = FakeTask()
        captured_tasks.append(task)
        return task

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )
    monkeypatch.setattr(evolution_handler, "build_msg_queue_task", capture_task)

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "approve"},
            }
        ),
        queue,
        channel=FakeChannel(),
    )

    assert queue.resume_calls == [
        ("agent-123", "latest-outbound-msg", captured_tasks[0])
    ]
    assert queue.tasks == []


@pytest.mark.asyncio
async def test_log_inbound_message_enqueues_when_latest_outbound_missing(monkeypatch):
    queue = FakeQueue()

    class FakeChannel:
        async def find_message_quoted_message_id(self, message_id):
            return None

        async def find_latest_outbound_message_id(self, remote_jid):
            return None

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hello"},
            }
        ),
        queue,
        channel=FakeChannel(),
    )

    assert queue.resume_calls == []
    assert len(queue.tasks) == 1


@pytest.mark.asyncio
async def test_log_inbound_message_enqueues_when_latest_outbound_resume_misses(monkeypatch):
    queue = FakeQueue(resume_return=False)

    class FakeChannel:
        async def find_message_quoted_message_id(self, message_id):
            return None

        async def find_latest_outbound_message_id(self, remote_jid):
            return "latest-outbound-msg"

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )

    await log_inbound_message(
        inbound(
            {
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"conversation": "hello"},
            }
        ),
        queue,
        channel=FakeChannel(),
    )

    assert len(queue.resume_calls) == 1
    assert queue.resume_calls[0][1] == "latest-outbound-msg"
    assert len(queue.tasks) == 1


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
async def test_log_inbound_message_task_callback_handles_interrupt_chunk(monkeypatch):
    sent_texts = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(
                StreamChunk(
                    chunk_type="interrupt",
                    data={
                        "type": "human_review",
                        "task_name": "Task tracker",
                        "goal": "Create root task tracking",
                        "message": "請確認是否執行任務",
                    },
                )
            )

    class FakeChannel:
        async def send_text(self, number, text, **options):
            sent_texts.append((number, text, options))
            return {"key": {"id": "sent-msg-1", "remoteJid": number}}

    async def resolve_agent_session(message):
        return "agent-123", "default-123"

    monkeypatch.setattr(
        evolution_handler, "resolve_whatsapp_agent_session", resolve_agent_session
    )

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

    assert len(sent_texts) == 1
    assert sent_texts[0][0] == "85298765432"
    assert sent_texts[0][1] == "請確認是否執行任務"


@pytest.mark.asyncio
async def test_log_inbound_message_task_callback_combines_agent_response_chunks(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="content", content="好"))
            await task.callback(StreamChunk(chunk_type="content", content="，主頁"))
            await task.callback(StreamChunk(chunk_type="content", content="！"))
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

    assert sent_messages == [("85298765432", "好，主頁！", {})]


@pytest.mark.asyncio
async def test_log_inbound_message_done_does_not_resend_agent_response(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="content", content="fallback"))
            assert sent_messages == []
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
async def test_whatsapp_task_callback_flushes_agent_response_on_task_end():
    sent_messages = []

    class FakeChannel:
        async def send_text(self, number, text, **options):
            sent_messages.append((number, text, options))
            return {"ok": True}

    task = WhatsAppMsgQueueTask(
        message="hi",
        agent_id="agent-123",
        session_id="default-123",
        channel=FakeChannel(),
        phone_no="85298765432",
    )

    await task.callback(StreamChunk(chunk_type="content", content="fallback"))
    assert sent_messages == []

    await task.callback(StreamChunk(chunk_type="task_end"))

    assert sent_messages == [("85298765432", "fallback", {})]


@pytest.mark.asyncio
async def test_log_inbound_message_task_callback_sends_tool_summary_as_separate_reply(monkeypatch):
    sent_messages = []

    class ResponseQueue:
        async def enqueue(self, task):
            await task.callback(StreamChunk(chunk_type="tool", content="search"))
            assert sent_messages == []
            await task.callback(StreamChunk(chunk_type="tool", content="memory"))
            assert sent_messages == []
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
async def test_whatsapp_task_callback_sends_assign_task_tool_before_interrupt_message():
    sent_messages = []

    class FakeChannel:
        async def send_text(self, number, text, **options):
            sent_messages.append((number, text, options))
            return {"key": {"id": f"sent-{len(sent_messages)}"}}

    task = WhatsAppMsgQueueTask(
        message="建立 task",
        agent_id="agent-123",
        session_id="default-123",
        channel=FakeChannel(),
        phone_no="85298765432",
    )

    await task.callback(StreamChunk(chunk_type="tool", content="assign_task"))
    await task.callback(StreamChunk(chunk_type="text_end"))
    await task.callback(
        StreamChunk(
            chunk_type="interrupt",
            data={
                "type": "human_review",
                "message": "我準備建立以下任務，請確認：\n\n任務名稱：Task tracker\n目標：Create root task tracking",
            },
        )
    )

    assert sent_messages == [
        ("85298765432", "🔧 已調用工具：assign_task\n", {}),
        (
            "85298765432",
            "我準備建立以下任務，請確認：\n\n任務名稱：Task tracker\n目標：Create root task tracking",
            {},
        ),
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
            "url": "http://evolution.test/chat/findMessages/Moss",
            "headers": {"apikey": "global-key"},
            "json": {"where": {"key": {"id": "msg-1"}}},
        },
        {
            "url": "http://evolution.test/chat/findMessages/Moss",
            "headers": {"apikey": "global-key"},
            "json": {
                "where": {"key": {"remoteJid": "85298765432@s.whatsapp.net"}}
            },
        },
        {
            "url": "http://evolution.test/message/sendText/Moss",
            "headers": {"apikey": "global-key"},
            "json": {"number": "85298765432", "text": "pong"},
        }
    ]
