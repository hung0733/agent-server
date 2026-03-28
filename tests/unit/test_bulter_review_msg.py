from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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

        agent_instance = SimpleNamespace(id=uuid4())
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
        assert captured["metadata"]["thread_id_override"].startswith("review-msg-")

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
