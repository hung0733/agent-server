from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk

from db.dto.memory_block_dto import MemoryBlock
from db.types import MessageType
from msg_queue.models import StreamChunk

sys.modules.setdefault("dateparser", types.SimpleNamespace(parse=lambda *_a, **_k: None))

from agent.bulter import Bulter


def _message(message_type: MessageType, content: str):
    return SimpleNamespace(
        id=uuid4(),
        message_type=message_type,
        content_json={"content": content},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )


async def _stream_with_content(content: str):
    yield StreamChunk(chunk_type="content", content=content)
    yield StreamChunk(chunk_type="done")


class TestBulterReviewMsg:
    async def test_send_emits_provider_usage_chunk_from_response_metadata(self, monkeypatch):
        endpoint_id = "00000000-0000-0000-0000-000000000099"
        task_id = "00000000-0000-0000-0000-000000000088"

        async def _fake_astream(*_args, **_kwargs):
            yield (
                AIMessageChunk(
                    content="hello",
                    response_metadata={
                        "token_usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 7,
                            "total_tokens": 19,
                        },
                        "model_name": "gpt-test",
                    },
                ),
                {"langgraph_node": "Butler"},
            )

        monkeypatch.setattr(
            "graph.graph_node.GraphNode.prepare_chat_node_config",
            lambda *_args, **_kwargs: {"configurable": {}},
        )
        monkeypatch.setattr(Bulter, "_graph", SimpleNamespace(astream=_fake_astream))

        butler = Bulter(
            agent_db_id="agent-db-1",
            session_db_id="session-db-1",
            agent_id="agent-001",
            session_id="session-001",
            involves_secrets=False,
            name="Butler",
        )

        chunks = []
        async for chunk in butler.send(
            models=[],
            sys_prompt="prompt",
            message="hello",
            think_mode=False,
            metadata={"llm_endpoint_id": endpoint_id, "task_id": task_id},
        ):
            chunks.append(chunk)

        assert [chunk.chunk_type for chunk in chunks] == ["content", "usage"]
        assert chunks[1].data == {
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
                "provider": None,
                "model": "gpt-test",
                "available": True,
                "llm_endpoint_id": endpoint_id,
                "task_id": task_id,
            }
        }

    async def test_send_falls_back_to_final_graph_state_usage(self, monkeypatch):
        async def _fake_astream(*_args, **_kwargs):
            yield (AIMessageChunk(content="hello"), {"langgraph_node": "Butler"})

        async def _fake_aget_state(_config):
            return SimpleNamespace(
                values={
                    "messages": [
                        AIMessage(
                            content="hello",
                            usage_metadata={
                                "input_tokens": 21,
                                "output_tokens": 4,
                                "total_tokens": 25,
                            },
                            response_metadata={
                                "model_name": "qwen-live",
                                "model_provider": "openai",
                            },
                        )
                    ]
                }
            )

        monkeypatch.setattr(
            "graph.graph_node.GraphNode.prepare_chat_node_config",
            lambda *_args, **_kwargs: {"configurable": {}},
        )
        monkeypatch.setattr(
            Bulter,
            "_graph",
            SimpleNamespace(astream=_fake_astream, aget_state=_fake_aget_state),
        )

        butler = Bulter(
            agent_db_id="agent-db-1",
            session_db_id="session-db-1",
            agent_id="agent-001",
            session_id="session-001",
            involves_secrets=False,
            name="Butler",
        )

        chunks = []
        async for chunk in butler.send(
            models=[],
            sys_prompt="prompt",
            message="hello",
            think_mode=False,
            metadata={},
        ):
            chunks.append(chunk)

        assert [chunk.chunk_type for chunk in chunks] == ["content", "usage"]
        assert chunks[1].data == {
            "usage": {
                "input_tokens": 21,
                "output_tokens": 4,
                "total_tokens": 25,
                "provider": None,
                "model": "qwen-live",
                "available": True,
            }
        }

    async def test_send_merges_final_state_metadata_into_stream_usage(self, monkeypatch):
        endpoint_id = "00000000-0000-0000-0000-000000000099"

        async def _fake_astream(*_args, **_kwargs):
            yield (
                AIMessageChunk(
                    content="hello",
                    usage_metadata={
                        "input_tokens": 12,
                        "output_tokens": 7,
                        "total_tokens": 19,
                    },
                ),
                {"langgraph_node": "Butler"},
            )

        async def _fake_aget_state(_config):
            return SimpleNamespace(
                values={
                    "messages": [
                        AIMessage(
                            content="hello",
                            usage_metadata={
                                "input_tokens": 12,
                                "output_tokens": 7,
                                "total_tokens": 19,
                            },
                            additional_kwargs={
                                "llm_endpoint_id": endpoint_id,
                                "model_name": "qwen-live",
                            },
                        )
                    ]
                }
            )

        monkeypatch.setattr(
            "graph.graph_node.GraphNode.prepare_chat_node_config",
            lambda *_args, **_kwargs: {"configurable": {}},
        )
        monkeypatch.setattr(
            Bulter,
            "_graph",
            SimpleNamespace(astream=_fake_astream, aget_state=_fake_aget_state),
        )

        butler = Bulter(
            agent_db_id="agent-db-1",
            session_db_id="session-db-1",
            agent_id="agent-001",
            session_id="session-001",
            involves_secrets=False,
            name="Butler",
        )

        chunks = []
        async for chunk in butler.send(
            models=[],
            sys_prompt="prompt",
            message="hello",
            think_mode=False,
            metadata={},
        ):
            chunks.append(chunk)

        assert chunks[1].data == {
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
                "provider": None,
                "model": "qwen-live",
                "available": True,
                "llm_endpoint_id": endpoint_id,
            }
        }

    def test_parse_review_msg_output_allows_empty_string(self):
        raw = (
            '{"SOUL":{"updated_data":""},'
            '"IDENTITY":{"updated_data":"identity"},'
            '"USER_PROFILE":{"updated_data":"profile"}}'
        )

        parsed = Bulter._parse_review_msg_output(raw)

        assert parsed["SOUL"] == ""

    async def test_review_msg_updates_only_changed_blocks(self, monkeypatch):
        grouped = {
            "2026-03-28": {
                "session-1": [
                    _message(MessageType.request, "User likes concise answers"),
                    _message(MessageType.response, "Got it"),
                ]
            }
        }

        agent_instance = SimpleNamespace(id=uuid4(), user_id=uuid4())
        existing_blocks = [
            MemoryBlock(
                id=uuid4(),
                agent_instance_id=agent_instance.id,
                memory_type="SOUL",
                content="original soul",
                version=2,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            MemoryBlock(
                id=uuid4(),
                agent_instance_id=agent_instance.id,
                memory_type="IDENTITY",
                content="same identity",
                version=3,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            MemoryBlock(
                id=uuid4(),
                agent_instance_id=agent_instance.id,
                memory_type="USER_PROFILE",
                content="original profile",
                version=1,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
        ]

        updated_soul = existing_blocks[0].model_copy(update={"content": "new soul", "version": 3})
        updated_profile = existing_blocks[2].model_copy(update={"content": "new profile", "version": 2})

        model_output = (
            '{"SOUL":{"updated_data":"new soul"},'
            '"IDENTITY":{"updated_data":"same identity"},'
            '"USER_PROFILE":{"updated_data":"new profile"}}'
        )

        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.get_unanalyzed_messages_grouped",
            AsyncMock(return_value=grouped),
        )
        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.batch_update_is_analyzed",
            AsyncMock(return_value=2),
        )
        monkeypatch.setattr(
            "db.dao.agent_instance_dao.AgentInstanceDAO.get_by_agent_id",
            AsyncMock(return_value=agent_instance),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.get_by_agent_instance_id",
            AsyncMock(return_value=existing_blocks),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.update",
            AsyncMock(side_effect=[updated_soul, updated_profile]),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.create",
            AsyncMock(),
        )
        create_session_mock = AsyncMock()
        monkeypatch.setattr(
            "db.dao.collaboration_session_dao.CollaborationSessionDAO.create",
            create_session_mock,
        )

        captured = {}

        def _fake_create_msg_queue(**kwargs):
            captured.update(kwargs)
            return _stream_with_content(model_output)

        monkeypatch.setattr(
            "msg_queue.handler.MsgQueueHandler.create_msg_queue",
            _fake_create_msg_queue,
        )

        result = await Bulter.review_msg("agent-001")

        assert result["processed_groups"] == 1
        assert result["failed_groups"] == 0
        assert result["messages_marked_analyzed"] == 2
        assert len(result["changed_blocks"]) == 2
        assert {item["memory_type"] for item in result["changed_blocks"]} == {
            "SOUL",
            "USER_PROFILE",
        }
        assert captured["session_id"] == "session-1"
        assert captured["metadata"]["thread_id_override"].startswith("review_msg-")
        assert create_session_mock.await_count == 1

    async def test_review_msg_returns_empty_when_no_messages(self, monkeypatch):
        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.get_unanalyzed_messages_grouped",
            AsyncMock(return_value={}),
        )

        result = await Bulter.review_msg("agent-001")

        assert result == {
            "total_groups": 0,
            "processed_groups": 0,
            "failed_groups": 0,
            "messages_marked_analyzed": 0,
            "changed_blocks": [],
        }

    async def test_review_msg_processes_session_in_token_chunks(self, monkeypatch):
        now = datetime.now(timezone.utc)
        msg1 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.request,
            content_json={"content": "m1"},
            created_at=now - timedelta(minutes=40),
        )
        msg2 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.response,
            content_json={"content": "m2"},
            created_at=now - timedelta(minutes=39),
        )
        msg3 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.request,
            content_json={"content": "m3"},
            created_at=now - timedelta(minutes=5),
        )
        msg4 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.response,
            content_json={"content": "m4"},
            created_at=now - timedelta(minutes=4),
        )
        grouped = {
            "2026-03-28": {
                "session-1": [msg1, msg2, msg3, msg4],
            }
        }

        agent_instance = SimpleNamespace(id=uuid4(), user_id=uuid4())
        original_soul = MemoryBlock(
            id=uuid4(),
            agent_instance_id=agent_instance.id,
            memory_type="SOUL",
            content="original soul",
            version=1,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        chunk1_soul = original_soul.model_copy(update={"content": "chunk1 soul", "version": 2})
        chunk2_soul = original_soul.model_copy(update={"content": "chunk2 soul", "version": 3})

        monkeypatch.setattr(
            "agent.bulter.Tools.get_token_count",
            lambda content_json: 1000 if content_json.get("content") in {"m1", "m2", "m3", "m4"} else 0,
        )
        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.get_unanalyzed_messages_grouped",
            AsyncMock(return_value=grouped),
        )
        monkeypatch.setattr(
            "db.dao.agent_instance_dao.AgentInstanceDAO.get_by_agent_id",
            AsyncMock(return_value=agent_instance),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.get_by_agent_instance_id",
            AsyncMock(side_effect=[[original_soul], [chunk1_soul]]),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.update",
            AsyncMock(side_effect=[chunk1_soul, chunk2_soul]),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.create",
            AsyncMock(),
        )
        mark_mock = AsyncMock(side_effect=[2, 2])
        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.batch_update_is_analyzed",
            mark_mock,
        )
        create_session_mock = AsyncMock()
        monkeypatch.setattr(
            "db.dao.collaboration_session_dao.CollaborationSessionDAO.create",
            create_session_mock,
        )

        model_outputs = [
            '{"SOUL":{"updated_data":"chunk1 soul"},"IDENTITY":{"updated_data":""},"USER_PROFILE":{"updated_data":""}}',
            '{"SOUL":{"updated_data":"chunk2 soul"},"IDENTITY":{"updated_data":""},"USER_PROFILE":{"updated_data":""}}',
        ]
        captured_messages = []

        def _fake_create_msg_queue(**kwargs):
            captured_messages.append(kwargs["message"])

            async def _stream():
                yield StreamChunk(
                    chunk_type="content",
                    content=model_outputs[len(captured_messages) - 1],
                )
                yield StreamChunk(chunk_type="done")

            return _stream()

        monkeypatch.setattr(
            "msg_queue.handler.MsgQueueHandler.create_msg_queue",
            _fake_create_msg_queue,
        )

        result = await Bulter.review_msg("agent-001")

        assert len(captured_messages) == 2
        assert "[SOUL]\noriginal soul" in captured_messages[0]
        assert "[SOUL]\nchunk1 soul" in captured_messages[1]
        assert mark_mock.await_count == 2
        assert create_session_mock.await_count == 2
        assert result["processed_groups"] == 1
        assert result["failed_groups"] == 0
        assert result["messages_marked_analyzed"] == 4

    async def test_review_msg_keeps_completed_chunks_when_later_chunk_fails(self, monkeypatch):
        now = datetime.now(timezone.utc)
        msg1 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.request,
            content_json={"content": "m1"},
            created_at=now - timedelta(minutes=40),
        )
        msg2 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.response,
            content_json={"content": "m2"},
            created_at=now - timedelta(minutes=39),
        )
        msg3 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.request,
            content_json={"content": "m3"},
            created_at=now - timedelta(minutes=5),
        )
        msg4 = SimpleNamespace(
            id=uuid4(),
            message_type=MessageType.response,
            content_json={"content": "m4"},
            created_at=now - timedelta(minutes=4),
        )
        grouped = {
            "2026-03-28": {
                "session-1": [msg1, msg2, msg3, msg4],
            }
        }

        agent_instance = SimpleNamespace(id=uuid4(), user_id=uuid4())
        original_soul = MemoryBlock(
            id=uuid4(),
            agent_instance_id=agent_instance.id,
            memory_type="SOUL",
            content="original soul",
            version=1,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        chunk1_soul = original_soul.model_copy(update={"content": "chunk1 soul", "version": 2})

        monkeypatch.setattr(
            "agent.bulter.Tools.get_token_count",
            lambda content_json: 1000 if content_json.get("content") in {"m1", "m2", "m3", "m4"} else 0,
        )
        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.get_unanalyzed_messages_grouped",
            AsyncMock(return_value=grouped),
        )
        monkeypatch.setattr(
            "db.dao.agent_instance_dao.AgentInstanceDAO.get_by_agent_id",
            AsyncMock(return_value=agent_instance),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.get_by_agent_instance_id",
            AsyncMock(side_effect=[[original_soul], [chunk1_soul]]),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.update",
            AsyncMock(return_value=chunk1_soul),
        )
        monkeypatch.setattr(
            "db.dao.memory_block_dao.MemoryBlockDAO.create",
            AsyncMock(),
        )
        mark_mock = AsyncMock(side_effect=[2])
        monkeypatch.setattr(
            "db.dao.agent_message_dao.AgentMessageDAO.batch_update_is_analyzed",
            mark_mock,
        )
        create_session_mock = AsyncMock()
        monkeypatch.setattr(
            "db.dao.collaboration_session_dao.CollaborationSessionDAO.create",
            create_session_mock,
        )

        call_count = 0

        def _fake_create_msg_queue(**_kwargs):
            async def _stream():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    yield StreamChunk(
                        chunk_type="content",
                        content='{"SOUL":{"updated_data":"chunk1 soul"},"IDENTITY":{"updated_data":""},"USER_PROFILE":{"updated_data":""}}',
                    )
                    yield StreamChunk(chunk_type="done")
                    return
                raise RuntimeError("llm failed")

            return _stream()

        monkeypatch.setattr(
            "msg_queue.handler.MsgQueueHandler.create_msg_queue",
            _fake_create_msg_queue,
        )

        result = await Bulter.review_msg("agent-001")

        assert call_count == 2
        assert result["processed_groups"] == 0
        assert result["failed_groups"] == 1
        assert result["messages_marked_analyzed"] == 2
        assert mark_mock.await_count == 1
        assert create_session_mock.await_count == 2
