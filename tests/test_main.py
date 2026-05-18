import asyncio

import pytest

import main as main_module
from backend.llm.types import StreamChunk


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
    migration_calls = []
    listener_calls = []
    monkeypatch.setattr(main_module, "_install_signal_handlers", lambda shutdown_event: None)

    async def run_listener(received_channel, llm_stream_handler=None):
        listener_calls.append((received_channel, llm_stream_handler))

    monkeypatch.setattr(main_module, "run_whatsapp_listener", run_listener)

    async def upgrade_database_schema():
        migration_calls.append(True)

    await main_module.main(
        db_engine=engine,
        channel_factory=lambda: channel,
        setup_logging_func=lambda: setup_calls.append(True),
        upgrade_database_schema_func=upgrade_database_schema,
        shutdown_event=asyncio.Event(),
    )

    assert setup_calls == [True]
    assert migration_calls == [True]
    assert listener_calls == [(channel, main_module.send_agent_message)]
    assert engine.executed == ["select 1"]
    assert channel.closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_upgrade_database_schema_runs_alembic_upgrade(monkeypatch):
    calls = []

    class FakeConfig:
        def __init__(self, path):
            self.path = path
            self.attributes = {}
            calls.append(("config", self, path))

        def set_main_option(self, key, value):
            calls.append(("set", self, key, value))

    def upgrade(config, revision):
        calls.append(("upgrade", config, revision))

    async def to_thread(func, *args):
        calls.append(("to_thread", func, args))
        return func(*args)

    monkeypatch.setattr(main_module, "Config", FakeConfig)
    monkeypatch.setattr(main_module.command, "upgrade", upgrade)
    monkeypatch.setattr(main_module.asyncio, "to_thread", to_thread)

    await main_module.upgrade_database_schema()

    config = calls[0][1]
    assert config.attributes == {"configure_logger": False}
    assert calls == [
        ("config", config, str(main_module.PROJECT_ROOT / "alembic.ini")),
        ("set", config, "script_location", str(main_module.PROJECT_ROOT / "alembic")),
        ("to_thread", upgrade, (config, "head")),
        ("upgrade", config, "head"),
    ]


@pytest.mark.asyncio
async def test_send_agent_message_calls_agent_send(monkeypatch):
    calls = []

    class FakeAgent:
        async def send(self, message, think_mode, metadata):
            calls.append((message, think_mode, metadata))
            yield StreamChunk(chunk_type="content", content="ok")

    async def get_agent(agent_id, session_id):
        calls.append((agent_id, session_id))
        return FakeAgent()

    monkeypatch.setattr(main_module.Agent, "get_agent", get_agent)

    chunks = [
        chunk
        async for chunk in main_module.send_agent_message(
            {
                "agent_id": "agent-1",
                "session_id": "session-1",
                "message": "hello",
                "files": None,
            }
        )
    ]

    assert calls == [
        ("agent-1", "session-1"),
        ("hello", False, {"source": "whatsapp"}),
    ]
    assert chunks == [StreamChunk(chunk_type="content", content="ok")]
