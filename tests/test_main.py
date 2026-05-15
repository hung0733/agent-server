import asyncio

import pytest

import main as main_module
from backend.channels.types import WhatsAppInboundMessage


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement):
        self.engine.executed.append(str(statement))


class FakeEngine:
    def __init__(self):
        self.executed = []
        self.disposed = False

    def connect(self):
        return FakeConnection(self)

    async def dispose(self):
        self.disposed = True


class FakeChannel:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.closed = False

    async def listen_messages(self):
        for message in self.messages:
            yield message

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_check_database_runs_select_one():
    engine = FakeEngine()

    await main_module.check_database(engine)

    assert engine.executed == ["select 1"]


def test_extract_message_metadata_from_whatsapp_payload():
    message = WhatsAppInboundMessage(
        event="messages.upsert",
        instance="sales-agent",
        data={"key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"}},
        raw={"instance": "sales-agent"},
    )

    assert main_module.extract_message_metadata(message) == ("msg-1", "85298765432@s.whatsapp.net")


def test_log_received_message_includes_content_metadata(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module.logger, "info", lambda *args: calls.append(args))
    received_message = main_module.EvolutionWhatsAppChannel().to_received_message(
        WhatsAppInboundMessage(
            event="messages.upsert",
            instance="sales-agent",
            data={
                "key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"},
                "message": {"imageMessage": {"caption": "image text"}},
            },
            raw={"instance": "sales-agent"},
        )
    )

    main_module.log_received_message(received_message)

    assert calls[0][1:] == (
        "sales-agent",
        "msg-1",
        "85298765432@s.whatsapp.net",
        "85298765432",
        "image",
        True,
        True,
    )


@pytest.mark.asyncio
async def test_run_whatsapp_listener_logs_inbound_metadata(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module.logger, "info", lambda *args: calls.append(args))
    channel = FakeChannel(
        [
            WhatsAppInboundMessage(
                event="messages.upsert",
                instance="sales-agent",
                data={"key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"}},
                raw={"instance": "sales-agent"},
            )
        ]
    )

    await main_module.run_whatsapp_listener(channel)

    assert any(
        args[1:]
        == (
            "sales-agent",
            "msg-1",
            "85298765432@s.whatsapp.net",
            "85298765432",
            "unknown",
            False,
            False,
        )
        for args in calls
    )


@pytest.mark.asyncio
async def test_main_starts_listener_and_cleans_up(monkeypatch):
    engine = FakeEngine()
    channel = FakeChannel(
        [
            WhatsAppInboundMessage(
                event="messages.upsert",
                instance="sales-agent",
                data={"key": {"id": "msg-1", "remoteJid": "85298765432@s.whatsapp.net"}},
                raw={"instance": "sales-agent"},
            )
        ]
    )
    setup_calls = []
    monkeypatch.setattr(main_module, "_install_signal_handlers", lambda shutdown_event: None)

    await main_module.main(
        db_engine=engine,
        channel_factory=lambda: channel,
        setup_logging_func=lambda: setup_calls.append(True),
        shutdown_event=asyncio.Event(),
    )

    assert setup_calls == [True]
    assert engine.executed == ["select 1"]
    assert channel.closed is True
    assert engine.disposed is True
