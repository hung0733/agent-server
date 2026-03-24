"""Unit tests for MessageQueue and MessageWorker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from channels.base import ChannelType, IncomingMessage
from msg_queue.message_queue import MessageQueue, MessageWorker


def _make_msg(
    msg_id: str = "id-1",
    sender: str = "85291234567",
    text: str = "hello",
    priority: int = 0,
) -> IncomingMessage:
    async def _noop(reply: str) -> None:
        pass

    return IncomingMessage(
        id=msg_id,
        channel=ChannelType.whatsapp,
        instance_id="test-instance",
        sender_id=sender,
        text=text,
        priority=priority,
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
        callback=_noop,
    )


class TestMessageQueue:

    async def test_put_and_get_single_message(self):
        q = MessageQueue()
        msg = _make_msg()
        await q.put(msg)
        result = await q.get()
        assert result.id == msg.id

    async def test_fifo_within_same_priority(self):
        q = MessageQueue()
        m1 = _make_msg("a", priority=0)
        m2 = _make_msg("b", priority=0)
        m3 = _make_msg("c", priority=0)
        await q.put(m1)
        await q.put(m2)
        await q.put(m3)
        assert (await q.get()).id == "a"
        assert (await q.get()).id == "b"
        assert (await q.get()).id == "c"

    async def test_higher_priority_dequeued_first(self):
        q = MessageQueue()
        low = _make_msg("low", priority=-1)
        normal = _make_msg("normal", priority=0)
        high = _make_msg("high", priority=1)
        critical = _make_msg("critical", priority=2)
        # Enqueue in worst order
        for m in (low, normal, high, critical):
            await q.put(m)
        assert (await q.get()).id == "critical"
        assert (await q.get()).id == "high"
        assert (await q.get()).id == "normal"
        assert (await q.get()).id == "low"

    async def test_mixed_priority_fifo_preserved(self):
        """Two high-priority messages arrive in order — FIFO within tier."""
        q = MessageQueue()
        h1 = _make_msg("h1", priority=1)
        h2 = _make_msg("h2", priority=1)
        l1 = _make_msg("l1", priority=0)
        await q.put(h1)
        await q.put(l1)
        await q.put(h2)
        assert (await q.get()).id == "h1"
        assert (await q.get()).id == "h2"
        assert (await q.get()).id == "l1"

    async def test_qsize(self):
        q = MessageQueue()
        assert q.qsize() == 0
        await q.put(_make_msg("x"))
        assert q.qsize() == 1
        await q.get()
        assert q.qsize() == 0

    async def test_empty(self):
        q = MessageQueue()
        assert q.empty() is True
        await q.put(_make_msg())
        assert q.empty() is False


class TestMessageWorker:

    async def test_worker_calls_handler(self):
        q = MessageQueue()
        received: list[str] = []

        async def handler(msg: IncomingMessage) -> None:
            received.append(msg.id)

        worker = MessageWorker(queue=q, handler=handler)
        await worker.start()
        await q.put(_make_msg("msg-1"))
        await q.put(_make_msg("msg-2"))
        # Give the worker a moment to drain
        await asyncio.sleep(0.05)
        await worker.stop()
        assert received == ["msg-1", "msg-2"]

    async def test_worker_continues_after_handler_exception(self):
        """A handler crash must not kill the worker loop."""
        q = MessageQueue()
        processed: list[str] = []

        async def flaky_handler(msg: IncomingMessage) -> None:
            if msg.id == "bad":
                raise ValueError("simulated error")
            processed.append(msg.id)

        worker = MessageWorker(queue=q, handler=flaky_handler)
        await worker.start()
        await q.put(_make_msg("bad"))
        await q.put(_make_msg("good"))
        await asyncio.sleep(0.05)
        await worker.stop()
        assert processed == ["good"]

    async def test_worker_stop_is_idempotent(self):
        q = MessageQueue()
        worker = MessageWorker(queue=q, handler=lambda m: asyncio.sleep(0))
        await worker.start()
        await worker.stop()
        await worker.stop()  # second stop should not raise

    async def test_worker_respects_priority(self):
        """Worker drains in priority order when queue is pre-filled."""
        q = MessageQueue()
        order: list[str] = []

        async def handler(msg: IncomingMessage) -> None:
            order.append(msg.id)

        # Fill queue before worker starts
        await q.put(_make_msg("low", priority=-1))
        await q.put(_make_msg("critical", priority=2))
        await q.put(_make_msg("normal", priority=0))

        worker = MessageWorker(queue=q, handler=handler)
        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

        assert order == ["critical", "normal", "low"]
