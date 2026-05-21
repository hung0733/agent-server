import asyncio

import pytest

import main as main_module
from backend.llm.types import StreamChunk
from backend.queues.msg_queue_handle import handle_agent_message


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
async def test_main_starts_message_queue_listener_and_cleans_up(monkeypatch):
    engine = FakeEngine()
    channel = FakeChannel()
    setup_calls = []
    migration_calls = []
    listener_calls = []
    queue_calls = []
    graph_calls = []
    monkeypatch.setattr(main_module, "_install_signal_handlers", lambda shutdown_event: None)

    class FakeQueue:
        def __init__(self, handler, max_concurrency):
            self.handler = handler
            self.max_concurrency = max_concurrency
            queue_calls.append(("init", handler, max_concurrency))

        def start(self):
            queue_calls.append(("start", self))

        async def stop(self):
            queue_calls.append(("stop", self))

    async def run_listener(received_channel, message_queue=None):
        listener_calls.append((received_channel, message_queue))

    async def upgrade_database_schema():
        migration_calls.append(True)

    async def init_checkpointer():
        graph_calls.append("init")

    class FakePool:
        async def close(self):
            graph_calls.append("close")

    monkeypatch.setattr(main_module, "MessageQueue", FakeQueue)
    monkeypatch.setattr(main_module, "run_whatsapp_listener", run_listener)
    monkeypatch.setattr(main_module.GraphStore, "init_langgraph_checkpointer", init_checkpointer)
    monkeypatch.setattr(main_module.GraphStore, "pool", FakePool())

    await main_module.main(
        db_engine=engine,
        channel_factory=lambda: channel,
        setup_logging_func=lambda: setup_calls.append(True),
        upgrade_database_schema_func=upgrade_database_schema,
        shutdown_event=asyncio.Event(),
    )

    queue = listener_calls[0][1]
    assert setup_calls == [True]
    assert migration_calls == [True]
    assert queue_calls == [
        ("init", main_module.handle_agent_message, 2),
        ("start", queue),
        ("stop", queue),
    ]
    assert listener_calls == [(channel, queue)]
    assert graph_calls == ["init", "close"]
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
async def test_handle_agent_message_calls_agent_send(monkeypatch):
    calls = []
    chunks = []

    class FakeTask:
        agent_id = "agent-1"
        session_id = "session-1"
        message = "hello"
        files = [{"mimetype": "text/plain", "filename": "a.txt", "bytes": b"a"}]

        async def callback(self, chunk):
            chunks.append(chunk)

    class FakeAgent:
        async def send(self, message, think_mode, metadata):
            calls.append((message, think_mode, metadata))
            yield StreamChunk(chunk_type="content", content="ok")
            yield StreamChunk(chunk_type="text_end")

    async def get_agent(agent_id, session_id):
        calls.append((agent_id, session_id))
        return FakeAgent()

    monkeypatch.setattr(main_module.handle_agent_message.__globals__["Agent"], "get_agent", get_agent)

    await handle_agent_message(FakeTask())

    assert calls == [
        ("agent-1", "session-1"),
        (
            "hello",
            False,
            {
                "source": "whatsapp",
                "files": [{"mimetype": "text/plain", "filename": "a.txt", "bytes": b"a"}],
            },
        ),
    ]
    assert chunks == [
        StreamChunk(chunk_type="content", content="ok"),
        StreamChunk(chunk_type="text_end"),
        StreamChunk(chunk_type="done"),
    ]
