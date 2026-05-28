from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.tdai_memory.config import MemoryConfig
from backend.tdai_memory.models import PipelineSessionState
from backend.tdai_memory.pipeline import scheduler as scheduler_module
from backend.tdai_memory.pipeline.scheduler import PipelineScheduler


class _FakePostgres:
    def __init__(self) -> None:
        self.written_states: list[PipelineSessionState] = []

    async def write_pipeline_state(self, state: PipelineSessionState) -> None:
        self.written_states.append(state.model_copy())

    async def count_l1(self, agent_id: str) -> int:
        return 0


class _FakeQueue:
    def __init__(self) -> None:
        self.items: list[tuple] = []

    async def enqueue(self, coro_factory, *args):
        self.items.append((coro_factory, args))


@pytest.mark.asyncio
async def test_trigger_l1_without_extracted_memories_does_not_queue_l2(monkeypatch, tmp_path):
    async def fake_run_l1_extraction(**kwargs):
        return []

    monkeypatch.setattr(scheduler_module, "run_l1_extraction", fake_run_l1_extraction)

    postgres = _FakePostgres()
    scheduler = PipelineScheduler(
        postgres=postgres,
        qdrant=object(),
        embedding=object(),
        llm_client=object(),
        config=MemoryConfig(),
        data_dir=str(tmp_path),
    )
    scheduler._l2_queue = _FakeQueue()

    state = PipelineSessionState(
        agent_id="agent-1",
        session_key="session-1",
        conversation_count=1,
        last_active_time=int(datetime.now(timezone.utc).timestamp() * 1000),
    )

    await scheduler._trigger_l1("agent-1", "session-1", state)

    assert state.conversation_count == 0
    assert state.l2_pending_l1_count == 0
    assert scheduler._l2_queue.items == []
    assert postgres.written_states[-1].l2_pending_l1_count == 0


@pytest.mark.asyncio
async def test_trigger_l2_without_scene_index_does_not_trigger_l3(monkeypatch, tmp_path):
    async def fake_run_l2_scene_grouping(**kwargs):
        return []

    monkeypatch.setattr(scheduler_module, "run_l2_scene_grouping", fake_run_l2_scene_grouping)

    postgres = _FakePostgres()
    scheduler = PipelineScheduler(
        postgres=postgres,
        qdrant=object(),
        embedding=object(),
        llm_client=object(),
        config=MemoryConfig(),
        data_dir=str(tmp_path),
    )
    state = PipelineSessionState(
        agent_id="agent-1",
        session_key="session-1",
        l2_pending_l1_count=1,
    )
    scheduler._sessions[("agent-1", "session-1")] = state

    l3_triggered = False

    async def fake_maybe_trigger_l3(agent_id: str) -> None:
        nonlocal l3_triggered
        l3_triggered = True

    scheduler._maybe_trigger_l3 = fake_maybe_trigger_l3

    await scheduler._trigger_l2("agent-1")

    assert state.l2_pending_l1_count == 0
    assert not l3_triggered
