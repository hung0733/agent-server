# Agent Type user_id & CRUD UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `user_id` to `agent_types` table for multi-tenant isolation and build full CRUD API + frontend UI for managing agent types.

**Architecture:** DB migration adds `user_id` FK + replaces `UNIQUE(name)` with `UNIQUE(user_id, name)`. Four new API endpoints handle list/create/update/delete with ownership checks. A new `AgentTypesTab` component replaces the placeholder in `AgentsPage`.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x async, Alembic, aiohttp, React 18, TypeScript, i18next, Vitest + Testing Library

---

## File Map

| Action | File |
|--------|------|
| Create | `alembic/versions/a2b3c4d5e6f7_add_user_id_to_agent_types.py` |
| Modify | `src/db/entity/agent_entity.py` |
| Modify | `src/db/dto/agent_dto.py` |
| Modify | `src/db/dao/agent_type_dao.py` |
| Modify | `src/api/app.py` |
| Modify | `tests/unit/test_api_app.py` |
| Modify | `frontend/src/types/dashboard.ts` |
| Modify | `frontend/src/api/dashboard.ts` |
| Modify | `frontend/src/mock/dashboard.ts` |
| Modify | `frontend/src/test/setup.ts` |
| Create | `frontend/src/components/agents/AgentTypesTab.tsx` |
| Create | `frontend/src/api/__tests__/agentTypes.test.ts` |
| Modify | `frontend/src/pages/AgentsPage.tsx` |
| Modify | `frontend/src/pages/__tests__/AgentsPage.test.tsx` |
| Modify | `frontend/src/i18n/locales/zh-HK/dashboard.json` |
| Modify | `frontend/src/i18n/locales/en/dashboard.json` |

---

## Task 1: DB Migration — add user_id to agent_types

**Files:**
- Create: `alembic/versions/a2b3c4d5e6f7_add_user_id_to_agent_types.py`

- [ ] **Step 1: Create the migration file**

```python
# alembic/versions/a2b3c4d5e6f7_add_user_id_to_agent_types.py
"""add_user_id_to_agent_types

Revision ID: a2b3c4d5e6f7
Revises: 9c1d7b4a2e6f
Create Date: 2026-03-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = '9c1d7b4a2e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agent_types', schema=None) as batch_op:
        # Drop old unique index and constraint on name alone
        batch_op.drop_index(batch_op.f('ix_agent_types_name'))
        batch_op.drop_constraint('uq_agent_types_name', type_='unique')

        # Add user_id column (nullable first so existing rows don't fail)
        batch_op.add_column(
            sa.Column('user_id', sa.UUID(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_agent_types_user_id',
            'users',
            ['user_id'],
            ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index('idx_agent_types_user_id', ['user_id'], unique=False)

        # Composite unique: one name per user
        batch_op.create_unique_constraint(
            'uq_agent_types_user_id_name', ['user_id', 'name']
        )

    # Make user_id NOT NULL after FK is set up
    # (safe if table is empty in all envs; if not, backfill first)
    op.execute(
        "ALTER TABLE agent_types ALTER COLUMN user_id SET NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table('agent_types', schema=None) as batch_op:
        batch_op.drop_constraint('uq_agent_types_user_id_name', type_='unique')
        batch_op.drop_index('idx_agent_types_user_id')
        batch_op.drop_constraint('fk_agent_types_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
        batch_op.create_unique_constraint('uq_agent_types_name', ['name'])
        batch_op.create_index(batch_op.f('ix_agent_types_name'), ['name'], unique=True)
```

- [ ] **Step 2: Run migration to verify it applies cleanly**

```bash
source .venv/bin/activate
alembic upgrade head
```

Expected: no errors, ends with `Running upgrade 9c1d7b4a2e6f -> a2b3c4d5e6f7`.

- [ ] **Step 3: Verify downgrade works**

```bash
alembic downgrade -1
alembic upgrade head
```

Expected: both commands succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/a2b3c4d5e6f7_add_user_id_to_agent_types.py
git commit -m "feat: add user_id to agent_types table"
```

---

## Task 2: Entity update — add user_id to AgentType

**Files:**
- Modify: `src/db/entity/agent_entity.py`

- [ ] **Step 1: Add user_id column to AgentType class**

In `src/db/entity/agent_entity.py`, inside `class AgentType`, add the `user_id` field after the `name` field and before `description`. Also update `__table_args__` to add the new index and swap the unique constraint.

Replace the entire `AgentType` class with:

```python
class AgentType(Base):
    """Agent type entity for categorizing agents.

    Table: agent_types
    """

    __tablename__ = "agent_types"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=gen_random_uuid,
        server_default=func.gen_random_uuid(),
    )
    """Primary key - UUID v4 generated by PostgreSQL."""

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Foreign key reference to the owning user."""

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=False,
    )
    """Name for the agent type (unique per user)."""

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    """Human-readable description of the agent type."""

    capabilities: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    """JSONB field storing agent capabilities as key-value pairs."""

    default_config: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    """JSONB field storing default configuration for this agent type."""

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    """Whether the agent type is currently active and available."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        server_default=func.now(),
    )
    """Record creation timestamp (UTC)."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        server_default=func.now(),
        onupdate=now_utc,
    )
    """Last update timestamp (UTC)."""

    __table_args__ = (
        Index("idx_agent_types_is_active", "is_active"),
        Index("idx_agent_types_user_id", "user_id"),
        {"extend_existing": True},
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/db/entity/agent_entity.py
git commit -m "feat: add user_id field to AgentType entity"
```

---

## Task 3: DTO update — add user_id to AgentType DTOs

**Files:**
- Modify: `src/db/dto/agent_dto.py`

- [ ] **Step 1: Add user_id to AgentTypeBase and AgentType DTOs**

In `src/db/dto/agent_dto.py`:

**In `AgentTypeBase`**, add `user_id` as the first field (before `name`):

```python
class AgentTypeBase(BaseModel):
    """Base model with common agent type fields."""

    user_id: UUID = Field(
        ...,
        description="ID of the owning user",
    )
    """Owning user ID."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique name for the agent type (per user)",
    )
    # ... rest unchanged
```

**`AgentTypeCreate`** inherits from `AgentTypeBase` — no changes needed.

**`AgentType`** (full DTO) inherits from `AgentTypeBase` — `user_id` is now included automatically. Update the `json_schema_extra` example to include `"user_id": "440d7300-d28a-30c3-9605-335544440000"`.

**`AgentTypeUpdate`** does NOT get `user_id` — ownership cannot be changed.

- [ ] **Step 2: Commit**

```bash
git add src/db/dto/agent_dto.py
git commit -m "feat: add user_id to AgentType DTOs"
```

---

## Task 4: DAO update — filter by user_id in get_all and pass user_id in create

**Files:**
- Modify: `src/db/dao/agent_type_dao.py`

- [ ] **Step 1: Update `create` to pass user_id to entity**

In `AgentTypeDAO.create`, update the entity construction:

```python
entity = AgentTypeEntity(
    user_id=dto.user_id,
    name=dto.name,
    description=dto.description,
    capabilities=dto.capabilities,
    default_config=dto.default_config,
    is_active=dto.is_active,
)
```

- [ ] **Step 2: Update `get_all` to accept and apply user_id filter**

Replace the `get_all` signature and `_query` inner function:

```python
@staticmethod
async def get_all(
    limit: int = 100,
    offset: int = 0,
    active_only: bool = False,
    user_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
) -> List[AgentType]:
    async def _query(s: AsyncSession) -> List[AgentTypeEntity]:
        query = select(AgentTypeEntity)
        if user_id is not None:
            query = query.where(AgentTypeEntity.user_id == user_id)
        if active_only:
            query = query.where(AgentTypeEntity.is_active.is_(True))
        query = query.limit(limit).offset(offset)
        result = await s.execute(query)
        return list(result.scalars().all())
    # ... rest of method unchanged
```

- [ ] **Step 3: Commit**

```bash
git add src/db/dao/agent_type_dao.py
git commit -m "feat: update AgentTypeDAO to filter by user_id"
```

---

## Task 5: API endpoints — CRUD for agent types

**Files:**
- Modify: `src/api/app.py`

- [ ] **Step 1: Add imports at top of app.py**

Add to the existing imports block:

```python
from db.dao.agent_type_dao import AgentTypeDAO
from db.dto.agent_dto import AgentTypeCreate, AgentTypeUpdate
```

- [ ] **Step 2: Add serializer helper**

After the `_serialize_auth_key` function (around line 263), add:

```python
def _serialize_agent_type(at) -> dict:
    return {
        "id": str(at.id),
        "name": at.name,
        "description": at.description,
        "isActive": at.is_active,
        "createdAt": at.created_at.isoformat() if at.created_at else None,
    }
```

- [ ] **Step 3: Add the four handler functions**

After `_serialize_agent_type`, add:

```python
async def _agent_types_list(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    items = await AgentTypeDAO.get_all(user_id=auth_context["user_id"])
    return web.json_response({"agentTypes": [_serialize_agent_type(i) for i in items]})


async def _agent_types_create(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()
    try:
        agent_type = await AgentTypeDAO.create(
            AgentTypeCreate(
                user_id=auth_context["user_id"],
                name=body["name"],
                description=body.get("description"),
                is_active=body.get("isActive", True),
            )
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise web.HTTPConflict(
                text=json.dumps({"error": "name_already_exists"}),
                content_type="application/json",
            )
        raise
    return web.json_response({"agentType": _serialize_agent_type(agent_type)}, status=201)


async def _agent_types_update(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_type_id = UUID(request.match_info["agent_type_id"])
    existing = await AgentTypeDAO.get_by_id(agent_type_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    body = await request.json()
    updated = await AgentTypeDAO.update(
        AgentTypeUpdate(
            id=agent_type_id,
            name=body.get("name"),
            description=body.get("description"),
            is_active=body.get("isActive"),
        )
    )
    if updated is None:
        raise web.HTTPNotFound()
    return web.json_response({"agentType": _serialize_agent_type(updated)})


async def _agent_types_delete(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_type_id = UUID(request.match_info["agent_type_id"])
    existing = await AgentTypeDAO.get_by_id(agent_type_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    await AgentTypeDAO.delete(agent_type_id)
    return web.json_response({"deleted": True})
```

- [ ] **Step 4: Register routes in `create_app`**

In `create_app`, after the line `app.router.add_patch("/api/dashboard/agents/{agent_id}/tools/{tool_id}", _agent_tool_update)`, add:

```python
    app.router.add_get("/api/dashboard/agent-types", _agent_types_list)
    app.router.add_post("/api/dashboard/agent-types", _agent_types_create)
    app.router.add_patch("/api/dashboard/agent-types/{agent_type_id}", _agent_types_update)
    app.router.add_delete("/api/dashboard/agent-types/{agent_type_id}", _agent_types_delete)
```

- [ ] **Step 5: Commit**

```bash
git add src/api/app.py
git commit -m "feat: add agent-type CRUD API endpoints"
```

---

## Task 6: Backend tests — agent type CRUD endpoints

**Files:**
- Modify: `tests/unit/test_api_app.py`

- [ ] **Step 1: Write the failing tests**

Add the following tests to `tests/unit/test_api_app.py`.

First, add `AgentTypeDAO` mock setup. At the top of the file, add:

```python
from unittest.mock import patch, AsyncMock
```

Then add the test class at the bottom of the file:

```python
@pytest.mark.asyncio
async def test_agent_types_list_returns_empty_for_user() -> None:
    user_id = uuid4()
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_all = AsyncMock(return_value=[])
        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/api/dashboard/agent-types", headers={"X-API-Key": "good-key"}
            )
            payload = await response.json()

    assert response.status == 200
    assert payload == {"agentTypes": []}
    mock_dao.get_all.assert_awaited_once_with(user_id=user_id)


@pytest.mark.asyncio
async def test_agent_types_create_returns_201() -> None:
    from datetime import datetime, timezone
    user_id = uuid4()
    type_id = uuid4()
    now = datetime.now(timezone.utc)

    class _FakeAgentType:
        id = type_id
        name = "TestType"
        description = "desc"
        is_active = True
        created_at = now
        user_id = user_id

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.create = AsyncMock(return_value=_FakeAgentType())
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/api/dashboard/agent-types",
                headers={"X-API-Key": "good-key"},
                json={"name": "TestType", "description": "desc"},
            )
            payload = await response.json()

    assert response.status == 201
    assert payload["agentType"]["name"] == "TestType"
    assert payload["agentType"]["description"] == "desc"
    assert payload["agentType"]["isActive"] is True


@pytest.mark.asyncio
async def test_agent_types_update_returns_updated() -> None:
    from datetime import datetime, timezone
    user_id = uuid4()
    type_id = uuid4()
    now = datetime.now(timezone.utc)

    class _FakeAgentType:
        id = type_id
        name = "Updated"
        description = None
        is_active = False
        created_at = now
        user_id = user_id

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_by_id = AsyncMock(return_value=_FakeAgentType())
        mock_dao.update = AsyncMock(return_value=_FakeAgentType())
        async with TestClient(TestServer(app)) as client:
            response = await client.patch(
                f"/api/dashboard/agent-types/{type_id}",
                headers={"X-API-Key": "good-key"},
                json={"name": "Updated", "isActive": False},
            )
            payload = await response.json()

    assert response.status == 200
    assert payload["agentType"]["name"] == "Updated"
    assert payload["agentType"]["isActive"] is False


@pytest.mark.asyncio
async def test_agent_types_update_returns_404_for_wrong_user() -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    type_id = uuid4()

    class _FakeAgentType:
        id = type_id
        user_id = other_user_id  # owned by different user

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_by_id = AsyncMock(return_value=_FakeAgentType())
        async with TestClient(TestServer(app)) as client:
            response = await client.patch(
                f"/api/dashboard/agent-types/{type_id}",
                headers={"X-API-Key": "good-key"},
                json={"name": "Hacked"},
            )

    assert response.status == 404


@pytest.mark.asyncio
async def test_agent_types_delete_returns_deleted_true() -> None:
    user_id = uuid4()
    type_id = uuid4()

    class _FakeAgentType:
        id = type_id
        user_id = user_id

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    with patch("api.app.AgentTypeDAO") as mock_dao:
        mock_dao.get_by_id = AsyncMock(return_value=_FakeAgentType())
        mock_dao.delete = AsyncMock(return_value=True)
        async with TestClient(TestServer(app)) as client:
            response = await client.delete(
                f"/api/dashboard/agent-types/{type_id}",
                headers={"X-API-Key": "good-key"},
            )
            payload = await response.json()

    assert response.status == 200
    assert payload == {"deleted": True}


@pytest.mark.asyncio
async def test_agent_types_require_auth() -> None:
    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
    )
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/dashboard/agent-types")

    assert response.status == 401
```

- [ ] **Step 2: Run failing tests to verify they fail for the right reason**

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_api_app.py::test_agent_types_list_returns_empty_for_user tests/unit/test_api_app.py::test_agent_types_create_returns_201 -v
```

Expected: FAIL (before Task 5 is done) or PASS (if Task 5 already done).

- [ ] **Step 3: Run all new tests**

```bash
python -m pytest tests/unit/test_api_app.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_api_app.py
git commit -m "test: add agent-type CRUD API endpoint tests"
```

---

## Task 7: Frontend types and API functions

**Files:**
- Modify: `frontend/src/types/dashboard.ts`
- Modify: `frontend/src/api/dashboard.ts`

- [ ] **Step 1: Add types to dashboard.ts**

At the end of `frontend/src/types/dashboard.ts`, add:

```typescript
export interface AgentTypeItem {
  id: string;
  name: string;
  description: string | null;
  isActive: boolean;
  createdAt: string;
}

export interface AgentTypesPayload {
  agentTypes: AgentTypeItem[];
}
```

- [ ] **Step 2: Add API functions to dashboard.ts**

At the end of `frontend/src/api/dashboard.ts`, add:

```typescript
export function fetchAgentTypes(): Promise<AgentTypesPayload> {
  return requestJson<AgentTypesPayload>("/api/dashboard/agent-types");
}

export function createAgentType(
  body: { name: string; description?: string; isActive?: boolean },
): Promise<{ agentType: AgentTypeItem }> {
  return mutateJson("/api/dashboard/agent-types", "POST", body);
}

export function updateAgentType(
  id: string,
  body: { name?: string; description?: string; isActive?: boolean },
): Promise<{ agentType: AgentTypeItem }> {
  return mutateJson(`/api/dashboard/agent-types/${id}`, "PATCH", body);
}

export function deleteAgentType(id: string): Promise<{ deleted: boolean }> {
  return mutateJson(`/api/dashboard/agent-types/${id}`, "DELETE", {});
}
```

Also add the import at the top of `dashboard.ts` (inside the existing import block):

```typescript
import {
  // existing imports ...
  AgentTypesPayload,
  AgentTypeItem,
} from "../types/dashboard";
```

- [ ] **Step 3: Write failing API function tests**

Create `frontend/src/api/__tests__/agentTypes.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchAgentTypes, createAgentType, updateAgentType, deleteAgentType } from "../dashboard";

const MOCK_TYPE = {
  id: "type-1",
  name: "TestType",
  description: "A test type",
  isActive: true,
  createdAt: "2026-03-31T00:00:00Z",
};

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ agentTypes: [MOCK_TYPE] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
});

describe("fetchAgentTypes", () => {
  it("calls GET /api/dashboard/agent-types", async () => {
    const result = await fetchAgentTypes();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types"),
      expect.objectContaining({}),
    );
    expect(result.agentTypes).toHaveLength(1);
    expect(result.agentTypes[0].name).toBe("TestType");
  });
});

describe("createAgentType", () => {
  it("calls POST /api/dashboard/agent-types with body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ agentType: MOCK_TYPE }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await createAgentType({ name: "TestType", description: "A test type" });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.agentType.name).toBe("TestType");
  });
});

describe("updateAgentType", () => {
  it("calls PATCH /api/dashboard/agent-types/:id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ agentType: { ...MOCK_TYPE, name: "Updated" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await updateAgentType("type-1", { name: "Updated" });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types/type-1"),
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(result.agentType.name).toBe("Updated");
  });
});

describe("deleteAgentType", () => {
  it("calls DELETE /api/dashboard/agent-types/:id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ deleted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await deleteAgentType("type-1");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types/type-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(result.deleted).toBe(true);
  });
});
```

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npm test -- --run src/api/__tests__/agentTypes.test.ts
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/dashboard.ts frontend/src/api/dashboard.ts frontend/src/api/__tests__/agentTypes.test.ts
git commit -m "feat: add AgentType frontend types and API functions"
```

---

## Task 8: i18n — add agent type strings

**Files:**
- Modify: `frontend/src/i18n/locales/zh-HK/dashboard.json`
- Modify: `frontend/src/i18n/locales/en/dashboard.json`

- [ ] **Step 1: Add keys to zh-HK/dashboard.json**

Add before the closing `}`:

```json
  "agents.agentType.addButton": "新增員工類型",
  "agents.agentType.editTitle": "編輯員工類型",
  "agents.agentType.createTitle": "新增員工類型",
  "agents.agentType.nameLabel": "名稱",
  "agents.agentType.namePlaceholder": "例如：研究型員工",
  "agents.agentType.descriptionLabel": "描述",
  "agents.agentType.descriptionPlaceholder": "簡短說明此員工類型的用途",
  "agents.agentType.isActiveLabel": "啟用",
  "agents.agentType.saveButton": "儲存",
  "agents.agentType.cancelButton": "取消",
  "agents.agentType.deleteConfirm": "確定刪除「{{name}}」？",
  "agents.agentType.colName": "名稱",
  "agents.agentType.colDescription": "描述",
  "agents.agentType.colActive": "啟用",
  "agents.agentType.colActions": "操作",
  "agents.agentType.editAction": "編輯",
  "agents.agentType.deleteAction": "刪除",
  "agents.agentType.empty": "尚未建立員工類型。",
  "agents.agentType.errorNameRequired": "名稱為必填。",
  "agents.agentType.errorNameExists": "此名稱已存在。"
```

- [ ] **Step 2: Add keys to en/dashboard.json**

Add before the closing `}`:

```json
  "agents.agentType.addButton": "New Agent Type",
  "agents.agentType.editTitle": "Edit Agent Type",
  "agents.agentType.createTitle": "New Agent Type",
  "agents.agentType.nameLabel": "Name",
  "agents.agentType.namePlaceholder": "e.g. Research Agent",
  "agents.agentType.descriptionLabel": "Description",
  "agents.agentType.descriptionPlaceholder": "Briefly describe this agent type",
  "agents.agentType.isActiveLabel": "Active",
  "agents.agentType.saveButton": "Save",
  "agents.agentType.cancelButton": "Cancel",
  "agents.agentType.deleteConfirm": "Delete \"{{name}}\"?",
  "agents.agentType.colName": "Name",
  "agents.agentType.colDescription": "Description",
  "agents.agentType.colActive": "Active",
  "agents.agentType.colActions": "Actions",
  "agents.agentType.editAction": "Edit",
  "agents.agentType.deleteAction": "Delete",
  "agents.agentType.empty": "No agent types created yet.",
  "agents.agentType.errorNameRequired": "Name is required.",
  "agents.agentType.errorNameExists": "This name already exists."
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/locales/zh-HK/dashboard.json frontend/src/i18n/locales/en/dashboard.json
git commit -m "feat: add agent type i18n strings"
```

---

## Task 9: Mock data and test setup

**Files:**
- Modify: `frontend/src/mock/dashboard.ts`
- Modify: `frontend/src/test/setup.ts`

- [ ] **Step 1: Add mock data to dashboard.ts**

In `frontend/src/mock/dashboard.ts`, add `AgentTypesPayload` and `AgentTypeItem` to the import block at the top:

```typescript
import {
  // existing imports...
  AgentTypesPayload,
  AgentTypeItem,
} from "../types/dashboard";
```

Then at the end of the file, add:

```typescript
export const agentTypesPayload: AgentTypesPayload = {
  agentTypes: [
    {
      id: "type-research",
      name: "研究型員工",
      description: "負責網絡搜尋與資料整理",
      isActive: true,
      createdAt: "2026-03-01T00:00:00Z",
    },
    {
      id: "type-assistant",
      name: "助理型員工",
      description: "處理日常行政與提醒工作",
      isActive: true,
      createdAt: "2026-03-02T00:00:00Z",
    },
  ],
};
```

- [ ] **Step 2: Update setup.ts to handle agent-types URL**

In `frontend/src/test/setup.ts`, add `agentTypesPayload` to the import and extend the URL dispatch logic:

```typescript
import {
  agentToolUpdatePayload,
  agentToolsPayload,
  agentTypesPayload,
  agentsPayload,
  memoryPayload,
  overviewPayload,
  settingsPayload,
  tasksPayload,
  usagePayload,
} from "../mock/dashboard";
```

In the `mockImplementation` function, extend the URL check chain. Replace the existing chain with:

```typescript
    if (url.includes("/api/dashboard/agents/") && url.includes("/tools/") && method === "PATCH") {
      return Promise.resolve(
        new Response(JSON.stringify(agentToolUpdatePayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.includes("/api/dashboard/agent-types")) {
      return Promise.resolve(
        new Response(JSON.stringify(agentTypesPayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    const payload = url.includes("/api/dashboard/usage")
      ? usagePayload
      : url.includes("/api/dashboard/agents/tools")
        ? agentToolsPayload
      : url.includes("/api/dashboard/agents")
        ? agentsPayload
      : url.includes("/api/dashboard/tasks")
        ? tasksPayload
          : url.includes("/api/dashboard/memory")
            ? memoryPayload
            : url.includes("/api/dashboard/settings")
              ? settingsPayload
              : overviewPayload;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/mock/dashboard.ts frontend/src/test/setup.ts
git commit -m "feat: add agent type mock data and test setup"
```

---

## Task 10: AgentTypesTab component

**Files:**
- Create: `frontend/src/components/agents/AgentTypesTab.tsx`

- [ ] **Step 1: Write the failing test first**

The test will be added in Task 11 (it imports `AgentTypesTab`). For now, create the component skeleton so TypeScript compiles:

Create `frontend/src/components/agents/AgentTypesTab.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  createAgentType,
  deleteAgentType,
  fetchAgentTypes,
  updateAgentType,
} from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { agentTypesPayload } from "../../mock/dashboard";
import type { AgentTypeItem, AgentTypesPayload } from "../../types/dashboard";

interface FormState {
  name: string;
  description: string;
  isActive: boolean;
}

const EMPTY_FORM: FormState = { name: "", description: "", isActive: true };

export default function AgentTypesTab() {
  const { t } = useTranslation();
  const { isLoading, resource } = useDashboardResource(fetchAgentTypes, agentTypesPayload, {
    blockOnFirstLoad: true,
  });

  const [items, setItems] = useState<AgentTypesPayload["agentTypes"]>(agentTypesPayload.agentTypes);
  const [editing, setEditing] = useState<AgentTypeItem | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Sync items when resource loads
  useState(() => {
    setItems(resource.agentTypes);
  });

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setShowForm(true);
  }

  function openEdit(item: AgentTypeItem) {
    setEditing(item);
    setForm({ name: item.name, description: item.description ?? "", isActive: item.isActive });
    setFormError(null);
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditing(null);
    setFormError(null);
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setFormError(t("agents.agentType.errorNameRequired"));
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        const result = await updateAgentType(editing.id, {
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          isActive: form.isActive,
        });
        setItems((prev) => prev.map((i) => (i.id === editing.id ? result.agentType : i)));
      } else {
        const result = await createAgentType({
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          isActive: form.isActive,
        });
        setItems((prev) => [...prev, result.agentType]);
      }
      closeForm();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("name_already_exists")) {
        setFormError(t("agents.agentType.errorNameExists"));
      } else {
        setFormError(msg);
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item: AgentTypeItem) {
    if (!window.confirm(t("agents.agentType.deleteConfirm", { name: item.name }))) return;
    await deleteAgentType(item.id);
    setItems((prev) => prev.filter((i) => i.id !== item.id));
  }

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入...</section>;
  }

  return (
    <section className="agent-types-tab">
      <div className="agent-types-header">
        <button className="btn btn-primary" onClick={openCreate}>
          {t("agents.agentType.addButton")}
        </button>
      </div>

      {items.length === 0 ? (
        <p className="agent-types-empty">{t("agents.agentType.empty")}</p>
      ) : (
        <table className="agent-types-table">
          <thead>
            <tr>
              <th>{t("agents.agentType.colName")}</th>
              <th>{t("agents.agentType.colDescription")}</th>
              <th>{t("agents.agentType.colActive")}</th>
              <th>{t("agents.agentType.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.name}</td>
                <td>{item.description ?? "—"}</td>
                <td>
                  <input type="checkbox" checked={item.isActive} readOnly aria-label={item.name} />
                </td>
                <td>
                  <button onClick={() => openEdit(item)}>
                    {t("agents.agentType.editAction")}
                  </button>
                  <button onClick={() => handleDelete(item)}>
                    {t("agents.agentType.deleteAction")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showForm && (
        <div role="dialog" aria-modal="true" className="agent-type-modal">
          <h2>{editing ? t("agents.agentType.editTitle") : t("agents.agentType.createTitle")}</h2>

          <label>
            {t("agents.agentType.nameLabel")}
            <input
              type="text"
              value={form.name}
              placeholder={t("agents.agentType.namePlaceholder")}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </label>

          <label>
            {t("agents.agentType.descriptionLabel")}
            <input
              type="text"
              value={form.description}
              placeholder={t("agents.agentType.descriptionPlaceholder")}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </label>

          <label>
            <input
              type="checkbox"
              checked={form.isActive}
              onChange={(e) => setForm((f) => ({ ...f, isActive: e.target.checked }))}
            />
            {t("agents.agentType.isActiveLabel")}
          </label>

          {formError && <p className="form-error">{formError}</p>}

          <div className="modal-actions">
            <button onClick={handleSave} disabled={saving}>
              {t("agents.agentType.saveButton")}
            </button>
            <button onClick={closeForm}>{t("agents.agentType.cancelButton")}</button>
          </div>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Commit skeleton**

```bash
git add frontend/src/components/agents/AgentTypesTab.tsx
git commit -m "feat: add AgentTypesTab component"
```

---

## Task 11: Wire AgentTypesTab into AgentsPage and update existing test

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx`
- Modify: `frontend/src/pages/__tests__/AgentsPage.test.tsx`

- [ ] **Step 1: Write the failing test additions**

In `frontend/src/pages/__tests__/AgentsPage.test.tsx`, add a new test for the agent type tab:

```tsx
  it("renders agent type table in the agent-type tab", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentsPage />);

    await user.click(await screen.findByRole("tab", { name: "員工類型" }));

    expect(await screen.findByRole("button", { name: "新增員工類型" })).toBeInTheDocument();
    expect(screen.getByText("研究型員工")).toBeInTheDocument();
    expect(screen.getByText("助理型員工")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd frontend && npm test -- --run src/pages/__tests__/AgentsPage.test.tsx
```

Expected: the new test FAILS (placeholder shown, not table).

- [ ] **Step 3: Update AgentsPage.tsx to use AgentTypesTab**

Replace the agent-type tab placeholder block in `frontend/src/pages/AgentsPage.tsx`:

Old:
```tsx
import AgentToolsTab from "../components/agents/AgentToolsTab";
```

New (add import):
```tsx
import AgentToolsTab from "../components/agents/AgentToolsTab";
import AgentTypesTab from "../components/agents/AgentTypesTab";
```

Replace:
```tsx
      {activeTab === "agent-type" ? (
        <article className="card agents-placeholder">
          <h3>{t("agents.tabs.agentType")}</h3>
          <p>{t("agents.tabs.placeholder")}</p>
        </article>
      ) : null}
```

With:
```tsx
      {activeTab === "agent-type" ? <AgentTypesTab /> : null}
```

- [ ] **Step 4: Run all frontend tests**

```bash
cd frontend && npm test -- --run
```

Expected: all tests PASS including the new agent-type tab test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx frontend/src/pages/__tests__/AgentsPage.test.tsx
git commit -m "feat: wire AgentTypesTab into AgentsPage"
```

---

## Task 12: Run full test suite

- [ ] **Step 1: Run all backend tests**

```bash
source .venv/bin/activate
python -m pytest tests/unit/ -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run all frontend tests**

```bash
cd frontend && npm test -- --run
```

Expected: all tests PASS.

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -p
git commit -m "fix: address test failures from final run"
```

Only needed if step 1 or 2 found issues.
