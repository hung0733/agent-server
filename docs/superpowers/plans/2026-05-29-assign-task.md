# Assign Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `assign_task` as a create-only Butler tool that stores a root task and three initial steps: Brainstorm, Planning, and Review.

**Architecture:** Add two SQLAlchemy entities with DTO/DAO wrappers, migrate PostgreSQL with Alembic, then implement `backend.tools.system.assign_task` using runtime config for user, agent, and session ids. The tool exposes only `task_name` and `goal`, writes root and step rows in one transaction, and returns generated external ids.

**Tech Stack:** Python 3.12, SQLAlchemy async ORM, Alembic, Pydantic, LangChain `@tool`, LangGraph `ToolRuntime`, pytest.

---

## File Structure

- Create `backend/entities/assigned_task.py`: SQLAlchemy models `AssignedTask` and `AssignedTaskStep`.
- Modify `backend/entities/__init__.py`: export/import the new entities so metadata includes both tables.
- Create `backend/dto/assigned_task.py`: Pydantic create/read DTOs for root tasks and steps.
- Modify `backend/dto/__init__.py`: export DTOs.
- Create `backend/dao/assigned_task.py`: DAO for creating a root task with Brainstorm, Planning, and Review rows.
- Modify `backend/dao/__init__.py`: export DAO.
- Create `alembic/versions/20260529_0010_add_assigned_task.py`: database migration.
- Modify `backend/i18n.py`: add zh_HK/en keys for tool descriptions, validation errors, and logs.
- Modify `backend/tools/system.py`: implement `assign_task`, input schema, validation helpers, id generation, and runtime extraction.
- Modify `backend/graph/graph_node.py`: include `assign_task` in the tool registry where Butler can call it.
- Modify `tests/test_data_layer.py`: metadata and DTO expectations.
- Modify `tests/test_tools_system.py`: replace old JSON payload expectations with create-only `task_name`/`goal` behavior.
- Modify `tests/test_agent_runtime.py`: update tool list expectations if `assign_task` appears in graph tool binding.

## Task 1: Database Models And Migration

**Files:**
- Create: `backend/entities/assigned_task.py`
- Modify: `backend/entities/__init__.py`
- Create: `alembic/versions/20260529_0010_add_assigned_task.py`
- Test: `tests/test_data_layer.py`

- [ ] **Step 1: Write failing metadata test**

Update `tests/test_data_layer.py` `EXPECTED_TABLES` to include the two new tables:

```python
EXPECTED_TABLES = {
    "agent",
    "agent_msg_hist",
    "assigned_task",
    "assigned_task_step",
    "llm_endpoint",
    "llm_group",
    "llm_level",
    "llm_usage",
    "session",
    "user_acc",
}
```

Run: `pytest tests/test_data_layer.py::test_entity_metadata_contains_expected_tables -v`

Expected: FAIL because `assigned_task` and `assigned_task_step` are missing from `Base.metadata.tables`.

- [ ] **Step 2: Add SQLAlchemy entities**

Create `backend/entities/assigned_task.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class AssignedTask(Base):
    __tablename__ = "assigned_task"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_acc.id"), nullable=False, index=True)
    responsible_agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("session.id"), nullable=True, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="brainstorm_pending", server_default="brainstorm_pending")
    approved_plan_html: Mapped[str | None] = mapped_column(Text)
    create_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    update_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("UserAcc")
    responsible_agent = relationship("Agent", foreign_keys=[responsible_agent_id])
    session = relationship("AgentSession")
    steps = relationship("AssignedTaskStep", back_populates="task", cascade="all, delete-orphan")


class AssignedTaskStep(Base):
    __tablename__ = "assigned_task_step"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    step_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("assigned_task.id"), nullable=False, index=True)
    parent_step_id: Mapped[int | None] = mapped_column(ForeignKey("assigned_task_step.id"), nullable=True, index=True)
    step_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    assign_agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("session.id"), nullable=True, index=True)
    output_html: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[str | None] = mapped_column(Text)
    create_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    update_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    task = relationship("AssignedTask", back_populates="steps")
    parent_step = relationship("AssignedTaskStep", remote_side=[id])
    assign_agent = relationship("Agent", foreign_keys=[assign_agent_id])
    session = relationship("AgentSession")
```

- [ ] **Step 3: Export entities**

Modify `backend/entities/__init__.py`:

```python
from backend.entities.agent import Agent
from backend.entities.agent_msg_hist import AgentMsgHist
from backend.entities.assigned_task import AssignedTask, AssignedTaskStep
from backend.entities.llm_endpoint import LlmEndpoint
from backend.entities.llm_group import LlmGroup
from backend.entities.llm_level import LlmLevel
from backend.entities.llm_usage import LlmUsage
from backend.entities.session import AgentSession
from backend.entities.user_acc import UserAcc

__all__ = [
    "Agent",
    "AgentMsgHist",
    "AgentSession",
    "AssignedTask",
    "AssignedTaskStep",
    "LlmEndpoint",
    "LlmGroup",
    "LlmLevel",
    "LlmUsage",
    "UserAcc",
]
```

- [ ] **Step 4: Add Alembic migration**

Create `alembic/versions/20260529_0010_add_assigned_task.py`:

```python
"""add assigned task tables

Revision ID: 20260529_0010
Revises: 20260528_0009
Create Date: 2026-05-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260529_0010"
down_revision: str | None = "20260528_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assigned_task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("responsible_agent_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=100), server_default="brainstorm_pending", nullable=False),
        sa.Column("approved_plan_html", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("update_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["responsible_agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_acc.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(op.f("ix_assigned_task_responsible_agent_id"), "assigned_task", ["responsible_agent_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_session_id"), "assigned_task", ["session_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_user_id"), "assigned_task", ["user_id"], unique=False)

    op.create_table(
        "assigned_task_step",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("parent_step_id", sa.Integer(), nullable=True),
        sa.Column("step_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("assign_agent_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("output_html", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("update_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assign_agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["parent_step_id"], ["assigned_task_step.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["assigned_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id"),
    )
    op.create_index(op.f("ix_assigned_task_step_assign_agent_id"), "assigned_task_step", ["assign_agent_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_step_parent_step_id"), "assigned_task_step", ["parent_step_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_step_session_id"), "assigned_task_step", ["session_id"], unique=False)
    op.create_index(op.f("ix_assigned_task_step_task_id"), "assigned_task_step", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_assigned_task_step_task_id"), table_name="assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_step_session_id"), table_name="assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_step_parent_step_id"), table_name="assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_step_assign_agent_id"), table_name="assigned_task_step")
    op.drop_table("assigned_task_step")
    op.drop_index(op.f("ix_assigned_task_user_id"), table_name="assigned_task")
    op.drop_index(op.f("ix_assigned_task_session_id"), table_name="assigned_task")
    op.drop_index(op.f("ix_assigned_task_responsible_agent_id"), table_name="assigned_task")
    op.drop_table("assigned_task")
```

- [ ] **Step 5: Verify metadata test passes**

Run: `pytest tests/test_data_layer.py::test_entity_metadata_contains_expected_tables -v`

Expected: PASS.

## Task 2: DTOs And DAO

**Files:**
- Create: `backend/dto/assigned_task.py`
- Modify: `backend/dto/__init__.py`
- Create: `backend/dao/assigned_task.py`
- Modify: `backend/dao/__init__.py`
- Test: `tests/test_data_layer.py`

- [ ] **Step 1: Write failing DTO validation test**

Add to `test_dto_validation_and_from_attributes` in `tests/test_data_layer.py`:

```python
    from backend.dto import AssignedTaskRead, AssignedTaskStepRead

    task_obj = type(
        "AssignedTaskObj",
        (),
        {
            "id": 1,
            "task_id": "task_abc123",
            "user_id": 1,
            "responsible_agent_id": 1,
            "session_id": 1,
            "task_name": "Build task tracker",
            "goal": "Create root task tracking",
            "status": "brainstorm_pending",
            "approved_plan_html": None,
        },
    )()
    assert AssignedTaskRead.model_validate(task_obj).task_id == "task_abc123"

    step_obj = type(
        "AssignedTaskStepObj",
        (),
        {
            "id": 1,
            "step_id": "step_abc123",
            "task_id": 1,
            "parent_step_id": None,
            "step_type": "brainstorm",
            "title": "Brainstorm",
            "goal": "Collect requirements",
            "status": "pending",
            "seq_no": 1,
            "assign_agent_id": 1,
            "session_id": None,
            "output_html": None,
            "output_json": None,
        },
    )()
    assert AssignedTaskStepRead.model_validate(step_obj).step_id == "step_abc123"
```

Run: `pytest tests/test_data_layer.py::test_dto_validation_and_from_attributes -v`

Expected: FAIL because DTOs are not exported.

- [ ] **Step 2: Add DTOs**

Create `backend/dto/assigned_task.py`:

```python
from pydantic import BaseModel, ConfigDict


class AssignedTaskCreate(BaseModel):
    task_id: str
    user_id: int
    responsible_agent_id: int
    session_id: int | None = None
    task_name: str
    goal: str
    status: str = "brainstorm_pending"
    approved_plan_html: str | None = None


class AssignedTaskRead(AssignedTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AssignedTaskStepCreate(BaseModel):
    step_id: str
    task_id: int
    parent_step_id: int | None = None
    step_type: str
    title: str
    goal: str
    status: str
    seq_no: int
    assign_agent_id: int
    session_id: int | None = None
    output_html: str | None = None
    output_json: str | None = None


class AssignedTaskStepRead(AssignedTaskStepCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
```

- [ ] **Step 3: Export DTOs**

Modify `backend/dto/__init__.py` to import and include:

```python
from backend.dto.assigned_task import (
    AssignedTaskCreate,
    AssignedTaskRead,
    AssignedTaskStepCreate,
    AssignedTaskStepRead,
)
```

Add these names to `__all__`:

```python
    "AssignedTaskCreate",
    "AssignedTaskRead",
    "AssignedTaskStepCreate",
    "AssignedTaskStepRead",
```

- [ ] **Step 4: Add DAO**

Create `backend/dao/assigned_task.py`:

```python
from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.dto.assigned_task import AssignedTaskStepCreate
from backend.entities.assigned_task import AssignedTask, AssignedTaskStep


class AssignedTaskDAO(BaseDAO[AssignedTask]):
    model = AssignedTask

    async def get_by_task_id(self, task_id: str) -> AssignedTask | None:
        stmt = select(AssignedTask).where(AssignedTask.task_id == task_id)
        return await self.session.scalar(stmt)

    async def create_initial_steps(
        self,
        *,
        task_db_id: int,
        assign_agent_id: int,
        step_ids: tuple[str, str, str],
    ) -> list[AssignedTaskStep]:
        definitions = [
            AssignedTaskStepCreate(
                step_id=step_ids[0],
                task_id=task_db_id,
                step_type="brainstorm",
                title="Brainstorm",
                goal="Collect requirements from the user, get approval, and produce an HTML plan document.",
                status="pending",
                seq_no=1,
                assign_agent_id=assign_agent_id,
            ),
            AssignedTaskStepCreate(
                step_id=step_ids[1],
                task_id=task_db_id,
                step_type="planning",
                title="Planning",
                goal="Convert the approved HTML plan into executable sub-steps.",
                status="blocked",
                seq_no=2,
                assign_agent_id=assign_agent_id,
            ),
            AssignedTaskStepCreate(
                step_id=step_ids[2],
                task_id=task_db_id,
                step_type="review",
                title="Review",
                goal="Review the planning output before execution starts.",
                status="blocked",
                seq_no=3,
                assign_agent_id=assign_agent_id,
            ),
        ]
        steps = [AssignedTaskStep(**definition.model_dump()) for definition in definitions]
        self.session.add_all(steps)
        await self.session.flush()
        for step in steps:
            await self.session.refresh(step)
        return steps
```

- [ ] **Step 5: Export DAO**

Modify `backend/dao/__init__.py` to import and include `AssignedTaskDAO`.

- [ ] **Step 6: Verify DTO test passes**

Run: `pytest tests/test_data_layer.py::test_dto_validation_and_from_attributes -v`

Expected: PASS.

## Task 3: assign_task Tool And i18n

**Files:**
- Modify: `backend/i18n.py`
- Modify: `backend/tools/system.py`
- Test: `tests/test_tools_system.py`

- [ ] **Step 1: Replace tool schema test with failing create-only schema test**

Update `tests/test_tools_system.py::test_assign_task_schema_exposes_only_task_json` to:

```python
def test_assign_task_schema_exposes_only_task_name_and_goal():
    schema = assign_task.args_schema.model_json_schema()

    assert assign_task.description == t("tools.system.assign_task.description")
    assert set(schema["properties"]) == {"task_name", "goal"}
    assert schema["required"] == ["task_name", "goal"]
    assert "runtime" not in schema["properties"]
    assert schema["properties"]["task_name"]["description"] == t(
        "tools.system.assign_task.task_name.description"
    )
    assert schema["properties"]["goal"]["description"] == t(
        "tools.system.assign_task.goal.description"
    )
```

Run: `pytest tests/test_tools_system.py::test_assign_task_schema_exposes_only_task_name_and_goal -v`

Expected: FAIL because current tool schema is not implemented.

- [ ] **Step 2: Add i18n keys**

Add zh_HK keys to `_MESSAGES["zh_HK"].update(...)` in `backend/i18n.py`:

```python
        "tools.system.assign_task.description": "建立一個可追蹤 root task，並自動建立 Brainstorm、Planning、Review 三個初始步驟。",
        "tools.system.assign_task.task_name.description": "任務名稱，用戶之後可用此名稱查詢任務現況。",
        "tools.system.assign_task.goal.description": "任務目標，描述用戶希望完成的結果。",
        "tools.system.assign_task.blank_task_name": "任務名稱不能為空",
        "tools.system.assign_task.blank_goal": "任務目標不能為空",
        "tools.system.assign_task.missing_runtime_user_id": "assign_task 缺少 user_db_id runtime 設定",
        "tools.system.assign_task.missing_runtime_agent_id": "assign_task 缺少 agent_db_id runtime 設定",
        "tools.system.assign_task.started": "開始建立 assigned task：tool_call_id=%s user_id=%s agent_id=%s task_name=%s",
        "tools.system.assign_task.completed": "完成建立 assigned task：tool_call_id=%s task_id=%s steps=%s",
```

Add en keys to `_MESSAGES["en"].update(...)`:

```python
        "tools.system.assign_task.description": "Create a trackable root task and automatically create Brainstorm, Planning, and Review initial steps.",
        "tools.system.assign_task.task_name.description": "Task name that the user can later use to enquire about progress.",
        "tools.system.assign_task.goal.description": "Task goal describing the intended outcome.",
        "tools.system.assign_task.blank_task_name": "Task name cannot be blank",
        "tools.system.assign_task.blank_goal": "Task goal cannot be blank",
        "tools.system.assign_task.missing_runtime_user_id": "assign_task is missing user_db_id runtime configuration",
        "tools.system.assign_task.missing_runtime_agent_id": "assign_task is missing agent_db_id runtime configuration",
        "tools.system.assign_task.started": "Creating assigned task: tool_call_id=%s user_id=%s agent_id=%s task_name=%s",
        "tools.system.assign_task.completed": "Created assigned task: tool_call_id=%s task_id=%s steps=%s",
```

- [ ] **Step 3: Implement tool**

Replace `backend/tools/system.py` with:

```python
import logging
import uuid
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field

from backend.dao.assigned_task import AssignedTaskDAO
from backend.db.session import async_session_factory
from backend.dto.assigned_task import AssignedTaskCreate
from backend.i18n import t

logger = logging.getLogger(__name__)


class AssignTaskArgs(BaseModel):
    task_name: str = Field(description=t("tools.system.assign_task.task_name.description"))
    goal: str = Field(description=t("tools.system.assign_task.goal.description"))


@tool(args_schema=AssignTaskArgs, description=t("tools.system.assign_task.description"))
async def assign_task(task_name: str, goal: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Create a trackable root task with initial workflow steps."""
    task_name = task_name.strip()
    goal = goal.strip()
    if not task_name:
        return {"accepted": False, "error": t("tools.system.assign_task.blank_task_name")}
    if not goal:
        return {"accepted": False, "error": t("tools.system.assign_task.blank_goal")}

    configurable = _configurable(runtime)
    user_db_id = _required_int(configurable, "user_db_id", t("tools.system.assign_task.missing_runtime_user_id"))
    agent_db_id = _required_int(configurable, "agent_db_id", t("tools.system.assign_task.missing_runtime_agent_id"))
    session_db_id = _optional_int(configurable, "session_db_id")
    task_external_id = _new_external_id("task")
    step_ids = (
        _new_external_id("step"),
        _new_external_id("step"),
        _new_external_id("step"),
    )

    logger.info(t("tools.system.assign_task.started"), runtime.tool_call_id, user_db_id, agent_db_id, task_name)

    async with async_session_factory() as session:
        dao = AssignedTaskDAO(session)
        task_row = await dao.create(
            AssignedTaskCreate(
                task_id=task_external_id,
                user_id=user_db_id,
                responsible_agent_id=agent_db_id,
                session_id=session_db_id,
                task_name=task_name,
                goal=goal,
            )
        )
        steps = await dao.create_initial_steps(
            task_db_id=task_row.id,
            assign_agent_id=agent_db_id,
            step_ids=step_ids,
        )
        await session.commit()

    logger.info(t("tools.system.assign_task.completed"), runtime.tool_call_id, task_external_id, len(steps))
    return {
        "accepted": True,
        "task_id": task_external_id,
        "task_name": task_name,
        "status": "brainstorm_pending",
        "steps": [
            {"step_id": step.step_id, "title": step.title, "status": step.status}
            for step in steps
        ],
    }


def _new_external_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _configurable(runtime: ToolRuntime) -> dict[str, Any]:
    return runtime.config.get("configurable", {}) if runtime.config else {}


def _required_int(configurable: dict[str, Any], key: str, error: str) -> int:
    value = configurable.get(key)
    if not isinstance(value, int):
        raise ValueError(error)
    return value


def _optional_int(configurable: dict[str, Any], key: str) -> int | None:
    value = configurable.get(key)
    return value if isinstance(value, int) else None


SystemTools = [assign_task]
```

- [ ] **Step 4: Replace validation tests**

In `tests/test_tools_system.py`, replace tests for JSON payload validation with tests for blank input:

```python
@pytest.mark.asyncio
async def test_assign_task_rejects_blank_task_name():
    result = await assign_task.coroutine(
        "   ",
        "Create root task tracking",
        _runtime({"user_db_id": 1, "agent_db_id": 1, "session_db_id": 1}),
    )

    assert result == {"accepted": False, "error": t("tools.system.assign_task.blank_task_name")}


@pytest.mark.asyncio
async def test_assign_task_rejects_blank_goal():
    result = await assign_task.coroutine(
        "Task tracker",
        "   ",
        _runtime({"user_db_id": 1, "agent_db_id": 1, "session_db_id": 1}),
    )

    assert result == {"accepted": False, "error": t("tools.system.assign_task.blank_goal")}
```

Ensure `_runtime` returns a `ToolRuntime` matching the existing helper style.

- [ ] **Step 5: Run focused tool tests**

Run: `pytest tests/test_tools_system.py -v`

Expected: tests still fail for DB creation because no fake session is patched yet. Schema and validation tests should pass.

## Task 4: Tool Persistence Tests

**Files:**
- Modify: `tests/test_tools_system.py`
- Modify only if needed: `backend/tools/system.py`

- [ ] **Step 1: Add async fake session and DAO integration test**

Add a test that uses the real DAO against the test database if existing test database fixtures are practical. If not, patch `async_session_factory` and `AssignedTaskDAO` with simple fakes to verify the tool orchestration:

```python
@pytest.mark.asyncio
async def test_assign_task_creates_root_task_and_initial_steps(monkeypatch):
    class FakeSession:
        committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            self.committed = True

    class FakeDAO:
        created_task = None
        created_steps = None

        def __init__(self, session):
            self.session = session

        async def create(self, data):
            self.created_task = data
            return type("TaskRow", (), {"id": 99})()

        async def create_initial_steps(self, *, task_db_id, assign_agent_id, step_ids):
            self.created_steps = (task_db_id, assign_agent_id, step_ids)
            return [
                type("StepRow", (), {"step_id": step_ids[0], "title": "Brainstorm", "status": "pending"})(),
                type("StepRow", (), {"step_id": step_ids[1], "title": "Planning", "status": "blocked"})(),
                type("StepRow", (), {"step_id": step_ids[2], "title": "Review", "status": "blocked"})(),
            ]

    fake_session = FakeSession()
    monkeypatch.setattr("backend.tools.system.async_session_factory", lambda: fake_session)
    monkeypatch.setattr("backend.tools.system.AssignedTaskDAO", FakeDAO)

    result = await assign_task.coroutine(
        "Task tracker",
        "Create root task tracking",
        _runtime({"user_db_id": 123, "agent_db_id": 456, "session_db_id": 789}),
    )

    assert result["accepted"] is True
    assert result["task_id"].startswith("task_")
    assert result["task_name"] == "Task tracker"
    assert result["status"] == "brainstorm_pending"
    assert [step["title"] for step in result["steps"]] == ["Brainstorm", "Planning", "Review"]
    assert [step["status"] for step in result["steps"]] == ["pending", "blocked", "blocked"]
    assert fake_session.committed is True
```

Run: `pytest tests/test_tools_system.py::test_assign_task_creates_root_task_and_initial_steps -v`

Expected: PASS after Task 3 implementation.

- [ ] **Step 2: Keep ToolNode injection test**

Update the existing ToolNode test message args to:

```python
"args": {"task_name": "Task tracker", "goal": "Create root task tracking"}
```

Invoke the graph with runtime config:

```python
config={"configurable": {"user_db_id": 123, "agent_db_id": 456, "session_db_id": 789}}
```

Patch `backend.tools.system.async_session_factory` and `backend.tools.system.AssignedTaskDAO` the same way as the persistence test, or assert only injection behavior with the fake patch active.

- [ ] **Step 3: Run system tool tests**

Run: `pytest tests/test_tools_system.py -v`

Expected: PASS.

## Task 5: Graph Tool Wiring

**Files:**
- Modify: `backend/graph/graph_node.py`
- Modify: `backend/graph/bulter.py`
- Test: `tests/test_agent_runtime.py`

- [ ] **Step 1: Write or update failing graph tool expectation**

In `tests/test_agent_runtime.py`, ensure Butler/supervisor graph tests expect `assign_task` to be available. Update assertions to include memory tools plus system tools according to current graph behavior. For example, when no sandbox exists, bound tool names should include:

```python
assert "assign_task" in [tool.name for tool in llm.bound_tools]
```

Run: `pytest tests/test_agent_runtime.py -k assign_task -v`

Expected: FAIL if `assign_task` is not wired.

- [ ] **Step 2: Import and expose SystemTools in graph node**

Modify `backend/graph/graph_node.py` imports:

```python
from backend.tools.system import SystemTools
```

Modify tool methods:

```python
    @staticmethod
    def get_all_tools() -> list[Any]:
        return SystemTools + MemoryTools + SandboxTools

    @staticmethod
    def build_tools(config: RunnableConfig, model: ChatOpenAI) -> ChatOpenAI:
        bind_tools = getattr(model, "bind_tools", None)
        if not callable(bind_tools):
            return model

        tools: Sequence[Any] = [] + SystemTools + MemoryTools
        if (GraphNode.get_configure(config, "sandbox")) is not None:
            tools += SandboxTools
```

- [ ] **Step 3: Update Butler graph tools if it bypasses GraphNode**

Modify `backend/graph/bulter.py`:

```python
from backend.tools.sandbox import SandboxTools
from backend.tools.system import SystemTools

...
workflow.add_node("tools", ToolNode(SystemTools + SandboxTools))
```

- [ ] **Step 4: Run focused runtime tests**

Run: `pytest tests/test_agent_runtime.py -k "assign_task or tool" -v`

Expected: PASS after expectations are aligned with the new graph tool list.

## Task 6: End-To-End Verification

**Files:**
- No new files unless a previous task reveals a missing import/export.

- [ ] **Step 1: Run targeted tests**

Run: `pytest tests/test_tools_system.py tests/test_data_layer.py tests/test_agent_runtime.py -v`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 3: Inspect git diff**

Run: `git diff -- backend/entities/assigned_task.py backend/entities/__init__.py backend/dto/assigned_task.py backend/dto/__init__.py backend/dao/assigned_task.py backend/dao/__init__.py backend/tools/system.py backend/graph/graph_node.py backend/graph/bulter.py backend/i18n.py tests/test_data_layer.py tests/test_tools_system.py tests/test_agent_runtime.py alembic/versions/20260529_0010_add_assigned_task.py`

Expected: diff only contains assign_task root-task implementation and related tests/schema changes.

## Self-Review Notes

- Spec coverage: this plan covers root task creation, three initial steps, DB schema, DTO/DAO, i18n, graph tool exposure, and tests. Enquire/update/fuzzy search/audit log/reusable review tool remain out of scope.
- Placeholder scan: no task relies on undefined placeholder behavior. Future agent dispatch is explicitly out of scope.
- Type consistency: root external id uses `task_id`; database integer FK from `assigned_task_step.task_id` points to `assigned_task.id`; step external id uses `step_id`; step agent field is `assign_agent_id`.
