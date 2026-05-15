import asyncio

import pytest

import main as main_module


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
    def __init__(self):
        self.closed = False

    async def listen_messages(self):
        if False:
            yield None

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_check_database_runs_select_one():
    engine = FakeEngine()

    await main_module.check_database(engine)

    assert engine.executed == ["select 1"]


@pytest.mark.asyncio
async def test_main_starts_listener_and_cleans_up(monkeypatch):
    engine = FakeEngine()
    channel = FakeChannel()
    setup_calls = []
    listener_calls = []
    monkeypatch.setattr(main_module, "_install_signal_handlers", lambda shutdown_event: None)

    async def run_listener(received_channel):
        listener_calls.append(received_channel)

    monkeypatch.setattr(main_module, "run_whatsapp_listener", run_listener)

    await main_module.main(
        db_engine=engine,
        channel_factory=lambda: channel,
        setup_logging_func=lambda: setup_calls.append(True),
        shutdown_event=asyncio.Event(),
    )

    assert setup_calls == [True]
    assert listener_calls == [channel]
    assert engine.executed == ["select 1"]
    assert channel.closed is True
    assert engine.disposed is True
