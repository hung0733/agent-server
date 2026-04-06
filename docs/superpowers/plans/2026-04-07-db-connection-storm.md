# DB Connection Storm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the PostgreSQL connection storm caused by per-chunk LTM pool creation and per-DAO-call engine creation, while preserving current DAO and scheduler APIs.

**Architecture:** Reuse one `MultiAgentMemorySystem` per `review_ltm()` run, make its cleanup defensive, and replace the current per-call SQLAlchemy engine creation pattern with a shared engine and shared session factory in `src/db/__init__.py`. Keep existing DAO method signatures intact so scheduler and agent code can continue using them unchanged.

**Tech Stack:** Python 3.12, asyncpg, SQLAlchemy asyncio, pytest

---

### Task 1: Add shared DB engine and session factory

**Files:**
- Modify: `src/db/__init__.py`
- Test: `tests/unit/test_db_shared_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from db import get_shared_engine, get_session_factory


def test_shared_engine_returns_same_instance():
    engine1 = get_shared_engine()
    engine2 = get_shared_engine()
    assert engine1 is engine2


def test_session_factory_returns_same_instance():
    factory1 = get_session_factory()
    factory2 = get_session_factory()
    assert factory1 is factory2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_db_shared_engine.py -v`
Expected: FAIL with import error because `get_shared_engine` and `get_session_factory` do not exist.

- [ ] **Step 3: Write minimal implementation**

Add shared module state and helpers in `src/db/__init__.py`:

```python
from typing import Optional

_shared_engine: Optional[AsyncEngine] = None
_shared_session_factory = None


def get_shared_engine() -> AsyncEngine:
    global _shared_engine
    if _shared_engine is None:
        _shared_engine = create_engine()
    return _shared_engine


def get_session_factory():
    global _shared_session_factory
    if _shared_session_factory is None:
        _shared_session_factory = async_sessionmaker(
            get_shared_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _shared_session_factory
```

Also extend `__all__` so these helpers are importable:

```python
__all__.extend(["get_dsn", "create_engine", "get_shared_engine", "get_session_factory"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_db_shared_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/db/__init__.py tests/unit/test_db_shared_engine.py
git commit -m "refactor: add shared db engine helpers"
```

### Task 2: Migrate AgentMessageDAO to shared sessions

**Files:**
- Modify: `src/db/dao/agent_message_dao.py`
- Test: `tests/unit/test_agent_message_dao_shared_session.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, patch

from db.dao.agent_message_dao import AgentMessageDAO


async def test_batch_update_is_summarized_uses_shared_session_factory():
    fake_session = AsyncMock()
    fake_result = AsyncMock()
    fake_result.rowcount = 2
    fake_session.execute.return_value = fake_result

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_factory = AsyncMock(return_value=_SessionCtx())

    with patch("db.dao.agent_message_dao.get_session_factory", return_value=fake_factory):
        count = await AgentMessageDAO.batch_update_is_summarized(message_ids=[1, 2], is_summarized=True)

    assert count == 2
    fake_session.execute.assert_awaited()
    fake_session.commit.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_agent_message_dao_shared_session.py -v`
Expected: FAIL because `agent_message_dao` still imports and uses `create_engine()`.

- [ ] **Step 3: Write minimal implementation**

Update `src/db/dao/agent_message_dao.py` imports and fallback path:

```python
from db import AsyncSession, async_sessionmaker, create_engine, get_session_factory
```

Replace this pattern:

```python
engine = create_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async with async_session() as s:
    count = await _batch_update(s)
await engine.dispose()
return count
```

With:

```python
session_factory = get_session_factory()
async with session_factory() as s:
    count = await _batch_update(s)
return count
```

Apply the same fallback change consistently to the other methods in this DAO that currently create and dispose an engine.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_agent_message_dao_shared_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/db/dao/agent_message_dao.py tests/unit/test_agent_message_dao_shared_session.py
git commit -m "refactor: reuse shared sessions in agent message dao"
```

### Task 3: Migrate task and agent DAOs on the failing stack traces

**Files:**
- Modify: `src/db/dao/task_dao.py`
- Modify: `src/db/dao/task_queue_dao.py`
- Modify: `src/db/dao/task_schedule_dao.py`
- Modify: `src/db/dao/agent_instance_dao.py`
- Modify: `src/db/dao/llm_level_endpoint_dao.py`
- Test: `tests/unit/test_db_dao_shared_session_regression.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_direct_dao_paths_do_not_create_and_dispose_engines_per_call():
    targets = [
        Path("src/db/dao/task_dao.py"),
        Path("src/db/dao/task_queue_dao.py"),
        Path("src/db/dao/task_schedule_dao.py"),
        Path("src/db/dao/agent_instance_dao.py"),
        Path("src/db/dao/llm_level_endpoint_dao.py"),
    ]
    for path in targets:
        text = path.read_text()
        assert "await engine.dispose()" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_db_dao_shared_session_regression.py -v`
Expected: FAIL because these DAOs still contain `await engine.dispose()`.

- [ ] **Step 3: Write minimal implementation**

In each DAO listed above:

1. Import `get_session_factory` from `db`.
2. Keep the `session is not None` branch unchanged.
3. Replace the fallback engine creation block with the shared session factory pattern.

Use this exact fallback template:

```python
session_factory = get_session_factory()
async with session_factory() as s:
    entity = await _query(s)
```

Use the same shape for create / update methods:

```python
session_factory = get_session_factory()
async with session_factory() as s:
    s.add(entity)
    await s.commit()
    await s.refresh(entity)
```

Do not change method signatures or DTO conversions.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_db_dao_shared_session_regression.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/db/dao/task_dao.py src/db/dao/task_queue_dao.py src/db/dao/task_schedule_dao.py src/db/dao/agent_instance_dao.py src/db/dao/llm_level_endpoint_dao.py tests/unit/test_db_dao_shared_session_regression.py
git commit -m "refactor: reuse shared sessions in scheduler daos"
```

### Task 4: Make MultiAgentMemorySystem cleanup defensive

**Files:**
- Modify: `src/ltm/simplemem.py`
- Test: `tests/unit/test_simplemem_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from ltm.simplemem import MultiAgentMemorySystem


@pytest.mark.asyncio
async def test_close_does_not_fail_when_initialize_never_completed():
    system = MultiAgentMemorySystem(agent_id="agent-1")
    await system.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_simplemem_cleanup.py -v`
Expected: FAIL with attribute error on `pg_pool`.

- [ ] **Step 3: Write minimal implementation**

In `src/ltm/simplemem.py`, initialize these attributes in `__init__()`:

```python
        self.qdrant_client = None
        self.pg_pool = None
        self.llm_client = None
        self.embedding_model = None
        self.vector_store = None
        self.pg_store = None
        self.memory_builder = None
        self.hybrid_retriever = None
        self.answer_generator = None
```

Update `close()` to guard against missing resources:

```python
    async def close(self):
        if self.pg_pool is not None:
            await self.pg_pool.close()
            self.pg_pool = None
            print("✅ Database connections closed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_simplemem_cleanup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ltm/simplemem.py tests/unit/test_simplemem_cleanup.py
git commit -m "fix: guard simplemem cleanup on failed init"
```

### Task 5: Reuse one LTM instance during review_ltm

**Files:**
- Modify: `src/agent/bulter.py`
- Test: `tests/unit/test_bulter_review_ltm_reuses_system.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, patch

import pytest

from agent.bulter import Bulter


@pytest.mark.asyncio
async def test_review_ltm_initializes_memory_system_once_per_run():
    fake_ltm = AsyncMock()
    fake_ltm.initialize = AsyncMock()
    fake_ltm.close = AsyncMock()

    grouped = {
        "2026-04-06": {
            "session-a": [AsyncMock(id=1), AsyncMock(id=2)],
            "session-b": [AsyncMock(id=3), AsyncMock(id=4)],
        }
    }

    with patch("agent.bulter.AgentMessageDAO.get_unsummarized_messages_grouped", new=AsyncMock(return_value=grouped)), \
         patch("agent.bulter.LLMLevelEndpointDAO.get_by_agent_instance_id", new=AsyncMock(return_value=[])), \
         patch("agent.bulter.LLMSet.from_model", return_value=AsyncMock()), \
         patch("agent.bulter.MultiAgentMemorySystem", return_value=fake_ltm), \
         patch("agent.bulter.Bulter._split_messages_by_tokens", return_value=[[AsyncMock(id=1)], [AsyncMock(id=2)]]), \
         patch("agent.bulter.Bulter._summary_ltm", new=AsyncMock(return_value=True)):
        await Bulter.review_ltm("agent-1")

    fake_ltm.initialize.assert_awaited_once()
    fake_ltm.close.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_bulter_review_ltm_reuses_system.py -v`
Expected: FAIL because `review_ltm()` currently creates the LTM instance inside `_summary_ltm()` instead of once per run.

- [ ] **Step 3: Write minimal implementation**

In `src/agent/bulter.py`:

1. Create one `MultiAgentMemorySystem` in `review_ltm()` after building `model_set`.
2. `await ltm.initialize()` once.
3. Pass `ltm` into `_summary_ltm()`.
4. Close `ltm` once in `review_ltm()` finally block.

Use this function signature update:

```python
    async def _summary_ltm(
        ltm: MultiAgentMemorySystem,
        agent_id: str,
        session_id: str,
        chunk: List[AgentMessage],
        receiver_agent_name: Optional[str] = None,
    ) -> bool:
```

Inside `_summary_ltm()`, remove the `MultiAgentMemorySystem(...)`, `await ltm.initialize()`, and `await ltm.close()` logic. Leave dialogue add / finalize / summarized update logic there.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_bulter_review_ltm_reuses_system.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/bulter.py tests/unit/test_bulter_review_ltm_reuses_system.py
git commit -m "refactor: reuse ltm system during review"
```

### Task 6: Remove unbounded background summarized updates

**Files:**
- Modify: `src/agent/bulter.py`
- Test: `tests/unit/test_bulter_summary_ltm_updates_inline.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, patch

import pytest

from agent.bulter import Bulter


@pytest.mark.asyncio
async def test_summary_ltm_updates_summarized_inline():
    msg = AsyncMock()
    msg.id = 1
    msg.message_type = "request"
    msg.content_json = {"content": "hello"}
    msg.created_at.isoformat.return_value = "2026-04-07T00:00:00+00:00"

    fake_ltm = AsyncMock()

    with patch("agent.bulter.AgentMessageDAO.batch_update_is_summarized", new=AsyncMock(return_value=1)) as batch_update, \
         patch("agent.bulter.Tools.start_async_task") as start_task:
        await Bulter._summary_ltm(fake_ltm, "agent-1", "session-1", [msg])

    batch_update.assert_awaited_once()
    start_task.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_bulter_summary_ltm_updates_inline.py -v`
Expected: FAIL because `_summary_ltm()` still calls `Tools.start_async_task()`.

- [ ] **Step 3: Write minimal implementation**

Replace this block in `src/agent/bulter.py`:

```python
            async def _batch_update_summarized():
                try:
                    count = await AgentMessageDAO.batch_update_is_summarized(
                        message_ids=message_ids,
                        is_summarized=True,
                    )
                    logger.info(_("✅ 已將 %d 條訊息標記為已摘要"), count)
                except Exception as e:
                    logger.error(_("❌ 批量更新 is_summarized 失敗: %s"), e, exc_info=True)

            Tools.start_async_task(_batch_update_summarized())
```

With:

```python
            count = await AgentMessageDAO.batch_update_is_summarized(
                message_ids=message_ids,
                is_summarized=True,
            )
            logger.info(_("✅ 已將 %d 條訊息標記為已摘要"), count)
```

Keep the existing `try/except` around `_summary_ltm()` so failures still get logged and return `False`.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_bulter_summary_ltm_updates_inline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/bulter.py tests/unit/test_bulter_summary_ltm_updates_inline.py
git commit -m "fix: update summarized flags inline"
```

### Task 7: Run targeted regression verification

**Files:**
- Modify: none
- Test: `tests/unit/test_db_shared_engine.py`
- Test: `tests/unit/test_agent_message_dao_shared_session.py`
- Test: `tests/unit/test_db_dao_shared_session_regression.py`
- Test: `tests/unit/test_simplemem_cleanup.py`
- Test: `tests/unit/test_bulter_review_ltm_reuses_system.py`
- Test: `tests/unit/test_bulter_summary_ltm_updates_inline.py`

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
source .venv/bin/activate && python -m pytest \
  tests/unit/test_db_shared_engine.py \
  tests/unit/test_agent_message_dao_shared_session.py \
  tests/unit/test_db_dao_shared_session_regression.py \
  tests/unit/test_simplemem_cleanup.py \
  tests/unit/test_bulter_review_ltm_reuses_system.py \
  tests/unit/test_bulter_summary_ltm_updates_inline.py -v
```

Expected: PASS.

- [ ] **Step 2: Run static search verification for forbidden per-call engine disposal**

Run:

```bash
source .venv/bin/activate && rg "await engine.dispose\(\)|engine = create_engine\(\)" src/db/dao src/agent/bulter.py
```

Expected:
- no matches in the DAOs migrated by this plan
- no LTM-specific create/dispose loop remains in `src/agent/bulter.py`

- [ ] **Step 3: Commit verification-only if needed**

```bash
git status --short
```

Expected: no uncommitted changes. If there are no changes, do not create an empty commit.

## Spec Coverage Check

- Shared engine and shared session factory: covered by Task 1.
- DAO fallback migration for failing stack paths: covered by Tasks 2 and 3.
- Defensive `MultiAgentMemorySystem` cleanup: covered by Task 4.
- Single LTM instance per `review_ltm()` run: covered by Task 5.
- Inline summarized update to reduce DB pressure: covered by Task 6.
- Verification of expected outcomes: covered by Task 7.

## Placeholder Scan

- No `TODO`, `TBD`, or deferred implementation placeholders remain.
- Each code-changing task includes concrete snippets and exact commands.
- Each verification step names exact files and expected outcomes.

## Type Consistency Check

- Shared DB helpers are consistently named `get_shared_engine` and `get_session_factory`.
- `_summary_ltm()` consistently accepts `ltm` as the first argument after refactor.
- DAO fallback path consistently uses `session_factory = get_session_factory()` and `async with session_factory() as s:`.
