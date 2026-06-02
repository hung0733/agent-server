import asyncio

import pytest

from backend.llm.types import StreamChunk
from backend.queues.message_queue import MessageQueue, MsgQueueTask, TaskState


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
        return True

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
        return True

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
        pass

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
            return True
        second_started.set()
        return True

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
        return True

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
        return True

    queue = MessageQueue(handler)
    task = RecordingTask("hello")

    await queue.enqueue(task)
    await queue._queue.join()
    await queue.stop()

    assert [chunk.chunk_type for chunk in task.chunks] == ["content", "done"]
    assert task.chunks[0].content == "hello"


@pytest.mark.asyncio
async def test_handler_sees_pending_state_for_new_task():
    handler_states = []

    async def handler(task):
        handler_states.append(task.task_state)
        return True

    queue = MessageQueue(handler)

    await queue.enqueue(RecordingTask("hello"))
    await queue._queue.join()
    await queue.stop()

    assert handler_states == [TaskState.PENDING]


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


@pytest.mark.asyncio
async def test_agent_processing_doesnt_block_other_agent():
    release_a1 = asyncio.Event()
    a2_started = asyncio.Event()

    async def handler(task):
        if task.agent_id == "agent-1":
            await release_a1.wait()
            return True
        if task.agent_id == "agent-2":
            a2_started.set()
            return True
        return True

    queue = MessageQueue(handler, max_concurrency=2)

    await queue.enqueue(RecordingTask("first", agent_id="agent-1"))
    await queue.enqueue(RecordingTask("second", agent_id="agent-2"))

    await asyncio.wait_for(a2_started.wait(), timeout=1)

    release_a1.set()
    await queue._queue.join()
    await queue.stop()


@pytest.mark.asyncio
async def test_task_state_transitions_to_interrupt():
    handler_ran = asyncio.Event()

    async def handler(task):
        task.wait_msg_id = "msg-123"
        handler_ran.set()
        return False

    queue = MessageQueue(handler, max_concurrency=1)
    task = RecordingTask("hello")
    await queue.enqueue(task)
    await asyncio.wait_for(handler_ran.wait(), timeout=1)
    await queue.stop()

    assert task.task_state == TaskState.INTERRUPT


@pytest.mark.asyncio
async def test_interrupt_blocks_new_pending_task():
    interrupt_done = asyncio.Event()
    pending_handler_ran = asyncio.Event()

    async def handler(task):
        if task.message == "interrupt_task":
            task.wait_msg_id = "msg-123"
            interrupt_done.set()
            return False
        pending_handler_ran.set()
        return True

    queue = MessageQueue(handler, max_concurrency=1)

    t1 = RecordingTask("interrupt_task", agent_id="agent-1")
    await queue.enqueue(t1)
    await asyncio.wait_for(interrupt_done.wait(), timeout=1)
    assert t1.task_state == TaskState.INTERRUPT

    t2 = RecordingTask("pending_task", agent_id="agent-1")
    await queue.enqueue(t2)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(pending_handler_ran.wait(), timeout=0.1)

    await queue.stop()


@pytest.mark.asyncio
async def test_resume_interrupt():
    interrupt_done = asyncio.Event()
    handled = []
    handler_states = []

    async def handler(task):
        handled.append(task.message)
        handler_states.append(task.task_state)
        if task.message == "interrupt_task" and handled.count(task.message) == 1:
            task.wait_msg_id = "msg-123"
            interrupt_done.set()
            return False
        return True

    queue = MessageQueue(handler, max_concurrency=2)

    t1 = RecordingTask("interrupt_task", agent_id="agent-1")
    await queue.enqueue(t1)
    await asyncio.wait_for(interrupt_done.wait(), timeout=1)
    assert t1.task_state == TaskState.INTERRUPT

    resumed = await queue.resume_interrupt(t1.agent_id, "msg-123")
    assert resumed is True
    assert t1.task_state == TaskState.RESUME
    assert t1.wait_msg_id is None

    await queue._queue.join()
    await queue.stop()

    assert handled == ["interrupt_task", "interrupt_task"]
    assert handler_states == [TaskState.PENDING, TaskState.RESUME]


@pytest.mark.asyncio
async def test_resume_interrupt_requires_matching_msg_id_and_agent_id():
    interrupt_done = asyncio.Event()
    pending_handler_ran = asyncio.Event()

    async def handler(task):
        if task.message == "interrupt_task":
            task.wait_msg_id = "msg-123"
            interrupt_done.set()
            return False
        pending_handler_ran.set()
        return True

    queue = MessageQueue(handler, max_concurrency=1)

    t1 = RecordingTask("interrupt_task", agent_id="agent-1")
    await queue.enqueue(t1)
    await asyncio.wait_for(interrupt_done.wait(), timeout=1)

    assert await queue.resume_interrupt("agent-1", "wrong-msg") is False
    assert await queue.resume_interrupt("wrong-agent", "msg-123") is False
    assert t1.task_state == TaskState.INTERRUPT
    assert t1.wait_msg_id == "msg-123"

    await queue.enqueue(RecordingTask("pending_task", agent_id="agent-1"))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(pending_handler_ran.wait(), timeout=0.1)

    await queue.stop()


@pytest.mark.asyncio
async def test_resume_interrupt_prioritizes_resume_task_before_pending_task():
    interrupt_done = asyncio.Event()
    handled = []

    async def handler(task):
        handled.append(task.message)
        if task.message == "interrupt_task" and handled.count(task.message) == 1:
            task.wait_msg_id = "msg-123"
            interrupt_done.set()
            return False
        return True

    queue = MessageQueue(handler, max_concurrency=1)

    t1 = RecordingTask("interrupt_task", agent_id="agent-1")
    await queue.enqueue(t1)
    await asyncio.wait_for(interrupt_done.wait(), timeout=1)

    await queue.enqueue(RecordingTask("pending_task", agent_id="agent-1"))
    assert await queue.resume_interrupt("agent-1", "msg-123") is True

    await queue._queue.join()
    await queue.stop()

    assert handled == ["interrupt_task", "interrupt_task", "pending_task"]
