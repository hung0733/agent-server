import asyncio

import pytest

from backend.llm.types import StreamChunk
from backend.queues.message_queue import MessagePayload, MessageQueue


def payload(message: str) -> MessagePayload:
    return {
        "agent_id": "agent-1",
        "session_id": "session-1",
        "message": message,
        "files": None,
    }


@pytest.mark.asyncio
async def test_create_msg_queue_yields_stream_chunks_and_done():
    async def handler(item):
        yield StreamChunk(chunk_type="content", content=item["message"])

    queue = MessageQueue(handler)

    chunks = [chunk async for chunk in queue.create_msg_queue(payload("hello"))]
    await queue.stop()

    assert [chunk.chunk_type for chunk in chunks] == ["content", "done"]
    assert chunks[0].content == "hello"


@pytest.mark.asyncio
async def test_message_queue_limits_concurrency_to_two():
    active = 0
    max_active = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(item):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if active == 2:
            entered.set()
        await release.wait()
        active -= 1
        yield StreamChunk(chunk_type="content", content=item["message"])

    queue = MessageQueue(handler, max_concurrency=2)

    tasks = [
        asyncio.create_task(_collect(queue.create_msg_queue(payload(str(index)))))
        for index in range(3)
    ]
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert max_active == 2

    release.set()
    await asyncio.gather(*tasks)
    await queue.stop()


@pytest.mark.asyncio
async def test_concurrent_streams_do_not_mix_chunks():
    async def handler(item):
        yield StreamChunk(chunk_type="content", content=item["message"])

    queue = MessageQueue(handler, max_concurrency=2)

    first, second = await asyncio.gather(
        _collect(queue.create_msg_queue(payload("first"))),
        _collect(queue.create_msg_queue(payload("second"))),
    )
    await queue.stop()

    assert [chunk.content for chunk in first if chunk.content] == ["first"]
    assert [chunk.content for chunk in second if chunk.content] == ["second"]


async def _collect(stream):
    return [chunk async for chunk in stream]
