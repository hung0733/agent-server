import asyncio

import pytest

from backend.llm.types import StreamChunk
from backend.queues.message_queue import MessageQueue, MsgQueueTask


class RecordingTask(MsgQueueTask):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            agent_id="agent-1",
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
async def test_message_queue_limits_concurrency_to_two():
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

    await queue.enqueue(RecordingTask("first"))
    await queue.enqueue(RecordingTask("second"))
    await queue.enqueue(RecordingTask("third"))
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert max_active == 2

    release.set()
    await queue._queue.join()
    await queue.stop()


@pytest.mark.parametrize("max_concurrency", [0, 3])
def test_message_queue_rejects_invalid_concurrency(max_concurrency):
    async def handler(task):
        return None

    with pytest.raises(ValueError):
        MessageQueue(handler, max_concurrency=max_concurrency)


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
