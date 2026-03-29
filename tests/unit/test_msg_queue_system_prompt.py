from __future__ import annotations

from decimal import Decimal
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

# Optional dependency in ltm stack is not needed for these unit tests.
sys.modules.setdefault("dateparser", types.SimpleNamespace(parse=lambda *_a, **_k: None))

from msg_queue.handler import MsgQueueHandler
from msg_queue.models import QueueTaskState
from msg_queue.task import QueueTask
from msg_queue.models import StreamChunk


class TestMsgQueueSystemPromptOverride:
    async def test_save_token_usage_persists_provider_usage(self, monkeypatch):
        user_id = uuid4()
        agent_id = uuid4()
        create_mock = AsyncMock()

        monkeypatch.setattr(
            "db.dao.collaboration_session_dao.CollaborationSessionDAO.get_by_session_id",
            AsyncMock(return_value=SimpleNamespace(user_id=user_id)),
        )
        monkeypatch.setattr(
            "db.dao.token_usage_dao.TokenUsageDAO.create",
            create_mock,
        )

        await MsgQueueHandler._save_token_usage(
            session_id="session-001",
            agent_db_id=str(agent_id),
            usage_payload={
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
                "provider": "openai",
                "model": "qwen3.5-35b-a3b",
                "available": True,
            },
        )

        dto = create_mock.await_args.args[0]
        assert dto.user_id == user_id
        assert dto.agent_id == agent_id
        assert dto.session_id == "session-001"
        assert dto.model_name == "qwen3.5-35b-a3b"
        assert dto.total_tokens == 19
        assert dto.estimated_cost_usd == Decimal("0")

    async def test_pack_memory_uses_system_prompt_when_provided(self):
        task = QueueTask(
            agent_id="agent-001",
            session_id="session-001",
            message="hello",
            system_prompt="override prompt",
        )
        task.agent = SimpleNamespace(get_memory_prompt=AsyncMock(return_value="unused"))

        await MsgQueueHandler.pack_memory(task)

        assert task.packed_prompt == "override prompt"
        assert task.state == QueueTaskState.PACKED_MEMORY
        task.agent.get_memory_prompt.assert_not_awaited()

    async def test_pack_memory_falls_back_to_default_memory_prompt(self):
        task = QueueTask(
            agent_id="agent-001",
            session_id="session-001",
            message="hello",
            system_prompt=None,
        )
        task.agent = SimpleNamespace(get_memory_prompt=AsyncMock(return_value="MEMORY\n"))

        await MsgQueueHandler.pack_memory(task)

        assert task.packed_prompt is not None
        assert task.packed_prompt.startswith("MEMORY\n")
        assert "現在時間:" in task.packed_prompt
        assert task.state == QueueTaskState.PACKED_MEMORY
        task.agent.get_memory_prompt.assert_awaited_once()

    async def test_pack_memory_treats_empty_string_as_explicit_override(self):
        task = QueueTask(
            agent_id="agent-001",
            session_id="session-001",
            message="hello",
            system_prompt="",
        )
        task.agent = SimpleNamespace(get_memory_prompt=AsyncMock(return_value="MEMORY\n"))

        await MsgQueueHandler.pack_memory(task)

        assert task.packed_prompt == ""
        assert task.state == QueueTaskState.PACKED_MEMORY
        task.agent.get_memory_prompt.assert_not_awaited()

    async def test_send_llm_msg_skips_persistence_for_review_msg(self, monkeypatch):
        async def _fake_stream():
            yield StreamChunk(chunk_type="content", content="{}")

        task = QueueTask(
            agent_id="agent-001",
            session_id="session-001",
            message="hello",
            metadata={"source": "review_msg"},
        )
        task.agent = SimpleNamespace(
            send=lambda **_kwargs: _fake_stream(),
            review_stm=AsyncMock(),
            session_db_id="00000000-0000-0000-0000-000000000001",
            agent_db_id="00000000-0000-0000-0000-000000000002",
        )
        task.model_set = object()
        task.packed_prompt = "prompt"
        task.packed_message = "message"

        started_tasks = []

        def _fake_start_async_task(coro):
            started_tasks.append(coro)
            try:
                coro.close()
            except Exception:
                pass

        monkeypatch.setattr("utils.tools.Tools.start_async_task", _fake_start_async_task)

        await MsgQueueHandler.send_llm_msg(task)

        assert started_tasks == []

    async def test_send_llm_msg_includes_provider_usage_in_completion_result(self):
        async def _fake_stream():
            yield StreamChunk(chunk_type="content", content="hello")
            yield StreamChunk(
                chunk_type="usage",
                data={
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 7,
                        "total_tokens": 19,
                        "provider": "openai",
                        "model": "gpt-test",
                        "available": True,
                    }
                },
            )

        task = QueueTask(
            agent_id="agent-001",
            session_id="session-001",
            message="hello",
            metadata={},
        )
        task.agent = SimpleNamespace(
            send=lambda **_kwargs: _fake_stream(),
            review_stm=AsyncMock(),
            session_db_id="00000000-0000-0000-0000-000000000001",
            agent_db_id="00000000-0000-0000-0000-000000000002",
        )
        task.model_set = object()
        task.packed_prompt = "prompt"
        task.packed_message = "message"
        complete_callback = AsyncMock()
        object.__setattr__(task, "complete_callback", complete_callback)

        await MsgQueueHandler.send_llm_msg(task)

        complete_callback.assert_awaited_once_with(
            {
                "task_id": task.id,
                "status": "completed",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 7,
                    "total_tokens": 19,
                    "provider": "openai",
                    "model": "gpt-test",
                    "available": True,
                },
            }
        )

    async def test_send_llm_msg_schedules_token_usage_persistence(self, monkeypatch):
        async def _fake_stream():
            yield StreamChunk(chunk_type="content", content="hello")
            yield StreamChunk(
                chunk_type="usage",
                data={
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 7,
                        "total_tokens": 19,
                        "provider": "openai",
                        "model": "qwen3.5-35b-a3b",
                        "available": True,
                    }
                },
            )

        task = QueueTask(
            agent_id="agent-001",
            session_id="session-001",
            message="hello",
            metadata={},
        )
        task.agent = SimpleNamespace(
            send=lambda **_kwargs: _fake_stream(),
            review_stm=AsyncMock(),
            session_db_id="00000000-0000-0000-0000-000000000001",
            agent_db_id="00000000-0000-0000-0000-000000000002",
        )
        task.model_set = object()
        task.packed_prompt = "prompt"
        task.packed_message = "message"

        started_coroutines = []

        def _fake_start_async_task(coro):
            started_coroutines.append(coro)
            try:
                coro.close()
            except Exception:
                pass

        monkeypatch.setattr("utils.tools.Tools.start_async_task", _fake_start_async_task)

        await MsgQueueHandler.send_llm_msg(task)

        assert len(started_coroutines) == 3
