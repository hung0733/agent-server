from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from db.dao.agent_message_dao import AgentMessageDAO
from db.types import MessageRedactionLevel, MessageType


class _FakeExecuteResult:
    def __init__(self, rowcount: int = 0, rows: list | None = None):
        self.rowcount = rowcount
        self._rows = rows or []

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, execute_result: _FakeExecuteResult):
        self._execute_result = execute_result
        self.committed = False

    async def execute(self, _stmt):
        return self._execute_result

    async def commit(self):
        self.committed = True


class TestAgentMessageDaoAnalyzedMethods:
    async def test_batch_update_is_analyzed_with_existing_session(self):
        message_ids = [uuid4(), uuid4(), uuid4()]
        session = _FakeSession(_FakeExecuteResult(rowcount=3))

        updated_count = await AgentMessageDAO.batch_update_is_analyzed(
            message_ids=message_ids,
            is_analyzed=True,
            session=session,
        )

        assert updated_count == 3
        assert session.committed is True

    async def test_get_unanalyzed_messages_grouped_with_existing_session(self):
        now = datetime.now(timezone.utc)
        entity_one = SimpleNamespace(
            id=uuid4(),
            collaboration_id=uuid4(),
            step_id="step-1",
            sender_agent_id=None,
            receiver_agent_id=None,
            message_type=MessageType.request,
            content_json={"content": "hi"},
            redaction_level=MessageRedactionLevel.none,
            is_summarized=False,
            is_analyzed=False,
            created_at=now - timedelta(hours=2),
        )
        entity_two = SimpleNamespace(
            id=uuid4(),
            collaboration_id=uuid4(),
            step_id="step-2",
            sender_agent_id=None,
            receiver_agent_id=None,
            message_type=MessageType.response,
            content_json={"content": "hello"},
            redaction_level=MessageRedactionLevel.none,
            is_summarized=False,
            is_analyzed=False,
            created_at=now - timedelta(hours=1),
        )
        rows = [
            (entity_one, "session-abc"),
            (entity_two, "session-abc"),
        ]
        session = _FakeSession(_FakeExecuteResult(rows=rows))

        grouped = await AgentMessageDAO.get_unanalyzed_messages_grouped(
            agent_id="agent-001",
            before_date=now,
            session=session,
        )

        assert len(grouped) == 1
        only_day = next(iter(grouped.values()))
        assert "session-abc" in only_day
        assert len(only_day["session-abc"]) == 2
