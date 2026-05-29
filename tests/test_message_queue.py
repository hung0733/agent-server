import asyncio

import pytest

from backend.llm.types import StreamChunk
from backend.queues.message_queue import MessageQueue, MsgQueueTask


class RecordingTask(MsgQueueTask):
    def __init__(self, message: str, agent_id: str = "agent-1"):
        super().__init__(
            message=message,
            agent_id=agent_id,
            session_id="session-1",
        )
        self.chunks = []

    async def callback(self, chunk):
        self.chunks.append(chunk)


@pytest.mark.asyncio
async def test_enqueue_dispatches_tasks_fifo():
    started = []

    async def handler(task):
        started.append(task.message)

    queue = MessageQueue(handler, max_concurrency=1)

    await queue.enqueue(RecordingTask("first"))
    await queue.enqueue(RecordingTask("second"))
    await queue.enqueue(RecordingTask("third"))
    await queue._queue.join()
    await queue.stop()

    assert started == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_message_queue_limits_global_concurrency():
    active = 0
    max_active = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(task):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if active == 2:
            entered.set()
        await release.wait()
        active -= 1

    queue = MessageQueue(handler, max_concurrency=2)

    await queue.enqueue(RecordingTask("first", agent_id="agent-1"))
    await queue.enqueue(RecordingTask("second", agent_id="agent-2"))
    await queue.enqueue(RecordingTask("third", agent_id="agent-3"))
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert max_active == 2

    release.set()
    await queue._queue.join()
    await queue.stop()


@pytest.mark.parametrize("max_concurrency", [0, -1])
def test_message_queue_rejects_invalid_concurrency(max_concurrency):
    async def handler(task):
        return None

    with pytest.raises(ValueError):
        MessageQueue(handler, max_concurrency=max_concurrency)


@pytest.mark.asyncio
async def test_message_queue_serializes_same_agent_id_tasks():
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()
    started = []

    async def handler(task):
        started.append(task.message)
        if task.message == "first":
            first_started.set()
            await release_first.wait()
            return
        second_started.set()

    queue = MessageQueue(handler, max_concurrency=4)

    await queue.enqueue(RecordingTask("first", agent_id="agent-1"))
    await queue.enqueue(RecordingTask("second", agent_id="agent-1"))
    await asyncio.wait_for(first_started.wait(), timeout=1)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(second_started.wait(), timeout=0.05)

    release_first.set()
    await queue._queue.join()
    await queue.stop()

    assert started == ["first", "second"]


@pytest.mark.asyncio
async def test_message_queue_runs_different_agent_id_tasks_concurrently():
    active = 0
    entered_two = asyncio.Event()
    release = asyncio.Event()

    async def handler(task):
        nonlocal active
        active += 1
        if active == 2:
            entered_two.set()
        await release.wait()
        active -= 1

    queue = MessageQueue(handler, max_concurrency=4)

    await queue.enqueue(RecordingTask("first", agent_id="agent-1"))
    await queue.enqueue(RecordingTask("second", agent_id="agent-2"))
    await asyncio.wait_for(entered_two.wait(), timeout=1)

    release.set()
    await queue._queue.join()
    await queue.stop()


@pytest.mark.asyncio
async def test_handler_calls_task_callback_with_chunks_and_done():
    async def handler(task):
        await task.callback(StreamChunk(chunk_type="content", content=task.message))
        await task.callback(StreamChunk(chunk_type="done"))

    queue = MessageQueue(handler)
    task = RecordingTask("hello")

    await queue.enqueue(task)
    await queue._queue.join()
    await queue.stop()

    assert [chunk.chunk_type for chunk in task.chunks] == ["content", "done"]
    assert task.chunks[0].content == "hello"


@pytest.mark.asyncio
async def test_handler_exception_callbacks_error_done():
    async def handler(task):
        raise RuntimeError("boom")

    queue = MessageQueue(handler)
    task = RecordingTask("hello")

    await queue.enqueue(task)
    await queue._queue.join()
    await queue.stop()

    assert len(task.chunks) == 1
    assert task.chunks[0].chunk_type == "done"
    assert task.chunks[0].data == {"error": "boom"}
