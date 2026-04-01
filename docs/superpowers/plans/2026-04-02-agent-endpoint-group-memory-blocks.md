# Agent Endpoint Group + Memory Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM Endpoint Group dropdown and SOUL / USER_PROFILE / IDENTITY memory block text areas to the agent add/edit modal.

**Architecture:** Inline approach — `POST /api/dashboard/agents` and the new `PATCH /api/dashboard/agents/{id}` both accept `endpointGroupId` + `memoryBlocks`; backend upserts memory blocks atomically after agent create/update. A new `GET /api/dashboard/agents/{agent_id}/memory-blocks` endpoint provides initial values for the edit modal. Frontend fetches memory blocks when opening the edit modal (non-blocking), and fetches endpoint groups from the existing settings API.

**Tech Stack:** Python 3.12 aiohttp (backend), React 18 + TypeScript (frontend), SQLAlchemy 2.x async, `MemoryBlockDAO`, `AgentInstanceDAO`

---

## File Map

| File | Change |
|------|--------|
| `src/db/dao/agent_instance_dao.py` | Add `endpoint_group_id` to entity constructor in `create()` |
| `src/db/dto/agent_dto.py` | Add `is_active` field to `AgentInstanceUpdate` |
| `src/api/app.py` | Update `_agents_create`, update `_serialize_agent_instance`, add `_agents_update`, add `_agents_get_memory_blocks`, register 2 new routes |
| `tests/unit/test_api_app.py` | Add 4 new test functions covering the new/updated routes |
| `frontend/src/types/dashboard.ts` | Add `MemoryBlocksInput`, extend `AgentCardData` / `AgentCreateBody` / `AgentUpdateBody` |
| `frontend/src/api/dashboard.ts` | Add `fetchAgentMemoryBlocks` |
| `frontend/src/components/agents/AgentTab.tsx` | Extend form state, fetch settings + memory blocks, add dropdown + 3 text areas |

---

## Task 1: Fix `AgentInstanceDAO.create` — persist `endpoint_group_id`

**Files:**
- Modify: `src/db/dao/agent_instance_dao.py:78-86`

The entity constructor in `AgentInstanceDAO.create` never passes `endpoint_group_id` to the entity, so it is always `NULL` after insert regardless of what is in the DTO.

- [ ] **Step 1: Read the current entity constructor call**

Open `src/db/dao/agent_instance_dao.py` and locate the block starting at line 78:

```python
entity = AgentInstanceEntity(
    agent_type_id=dto.agent_type_id,
    user_id=dto.user_id,
    name=dto.name,
    status=dto.status,
    config=dto.config,
    last_heartbeat_at=dto.last_heartbeat_at,
    is_sub_agent=dto.is_sub_agent,
)
```

- [ ] **Step 2: Add `endpoint_group_id` to the constructor**

Replace the block above with:

```python
entity = AgentInstanceEntity(
    agent_type_id=dto.agent_type_id,
    user_id=dto.user_id,
    name=dto.name,
    status=dto.status,
    config=dto.config,
    last_heartbeat_at=dto.last_heartbeat_at,
    is_sub_agent=dto.is_sub_agent,
    endpoint_group_id=dto.endpoint_group_id,
)
```

- [ ] **Step 3: Commit**

```bash
git add src/db/dao/agent_instance_dao.py
git commit -m "fix: persist endpoint_group_id in AgentInstanceDAO.create"
```

---

## Task 2: Add `is_active` to `AgentInstanceUpdate` DTO

**Files:**
- Modify: `src/db/dto/agent_dto.py` (class `AgentInstanceUpdate`, after line ~362)

The `AgentInstanceUpdate` DTO currently has no `is_active` field. The frontend sends `isActive` in update payloads; without this the field is silently ignored.

- [ ] **Step 1: Add `is_active` to `AgentInstanceUpdate`**

In `src/db/dto/agent_dto.py`, inside `class AgentInstanceUpdate`, add after the `is_sub_agent` field (around line 362):

```python
    is_active: Optional[bool] = Field(
        default=None,
        description="New active flag (False = soft-deleted)",
    )
    """Soft-delete flag (optional)."""
```

- [ ] **Step 2: Run existing DTO tests**

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_agent_dto_sub_agent.py -v
```

Expected: all tests PASS (no regressions).

- [ ] **Step 3: Commit**

```bash
git add src/db/dto/agent_dto.py
git commit -m "feat: add is_active to AgentInstanceUpdate DTO"
```

---

## Task 3: Backend — update `_agents_create` and `_serialize_agent_instance`

**Files:**
- Modify: `src/api/app.py`
- Test: `tests/unit/test_api_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_api_app.py`:

```python
@pytest.mark.asyncio
async def test_agents_create_accepts_endpoint_group_and_memory_blocks(monkeypatch) -> None:
    user_id = uuid4()
    agent_type_id = uuid4()
    agent_id_val = uuid4()
    endpoint_group_id = uuid4()

    fake_type = type("AgentType", (), {"id": agent_type_id, "user_id": user_id})()
    fake_agent = type(
        "Agent",
        (),
        {
            "id": agent_id_val,
            "name": "Butler",
            "agent_type_id": agent_type_id,
            "status": "idle",
            "phone_no": None,
            "whatsapp_key": None,
            "is_sub_agent": False,
            "is_active": True,
            "agent_id": f"agent-{agent_id_val}",
            "endpoint_group_id": endpoint_group_id,
            "created_at": None,
        },
    )()
    fake_session = type("Session", (), {"id": uuid4()})()
    fake_block = type("Block", (), {"id": uuid4()})()

    monkeypatch.setattr("api.app.AgentTypeDAO.get_by_id", AsyncMock(return_value=fake_type))
    monkeypatch.setattr("api.app.AgentInstanceDAO.create", AsyncMock(return_value=fake_agent))
    monkeypatch.setattr(
        "api.app.CollaborationSessionDAO.create", AsyncMock(return_value=fake_session)
    )
    monkeypatch.setattr("api.app.MemoryBlockDAO.create", AsyncMock(return_value=fake_block))
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id", AsyncMock(return_value=[])
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.post(
            "/api/dashboard/agents",
            headers={"X-API-Key": "good-key"},
            json={
                "name": "Butler",
                "agentTypeId": str(agent_type_id),
                "endpointGroupId": str(endpoint_group_id),
                "memoryBlocks": {"SOUL": "你是一個友善的助手", "USER_PROFILE": "", "IDENTITY": ""},
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 201
    assert payload["agent"]["endpointGroupId"] == str(endpoint_group_id)
    # Only SOUL was non-empty — MemoryBlockDAO.create called once
    from api.app import MemoryBlockDAO
    assert MemoryBlockDAO.create.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_api_app.py::test_agents_create_accepts_endpoint_group_and_memory_blocks -v
```

Expected: FAIL (ImportError or KeyError — `endpointGroupId` not in response, `MemoryBlockDAO` not imported in app.py).

- [ ] **Step 3: Update `app.py` imports**

At the top of `src/api/app.py`, add these two imports alongside the existing DAO imports:

```python
from db.dao.memory_block_dao import MemoryBlockDAO
from db.dto.agent_dto import AgentInstanceUpdate
from db.dto.memory_block_dto import MemoryBlockCreate, MemoryBlockUpdate
```

Also add `AgentInstanceUpdate` to the existing agent_dto import line (it currently only imports `AgentTypeCreate, AgentTypeUpdate, AgentInstanceCreate`):

```python
from db.dto.agent_dto import AgentTypeCreate, AgentTypeUpdate, AgentInstanceCreate, AgentInstanceUpdate
```

- [ ] **Step 4: Update `_serialize_agent_instance`**

Replace the existing function:

```python
def _serialize_agent_instance(agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "agentTypeId": str(agent.agent_type_id) if agent.agent_type_id else None,
        "status": agent.status,
        "phoneNo": agent.phone_no,
        "whatsappKey": agent.whatsapp_key,
        "isSubAgent": agent.is_sub_agent,
        "isActive": agent.is_active,
        "agentId": agent.agent_id,
        "createdAt": agent.created_at.isoformat() if agent.created_at else None,
    }
```

With:

```python
def _serialize_agent_instance(agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "agentTypeId": str(agent.agent_type_id) if agent.agent_type_id else None,
        "status": agent.status,
        "phoneNo": agent.phone_no,
        "whatsappKey": agent.whatsapp_key,
        "isSubAgent": agent.is_sub_agent,
        "isActive": agent.is_active,
        "agentId": agent.agent_id,
        "endpointGroupId": str(agent.endpoint_group_id) if agent.endpoint_group_id else None,
        "createdAt": agent.created_at.isoformat() if agent.created_at else None,
    }
```

- [ ] **Step 5: Add `_upsert_memory_blocks` helper**

Add this helper function just before `_agents_create` in `src/api/app.py`:

```python
async def _upsert_memory_blocks(agent_instance_id: UUID, memory_blocks: dict) -> None:
    """Create or update memory blocks for an agent instance.

    Only processes non-empty content values. Matches existing blocks by
    memory_type and updates them; creates new blocks when none exist.
    """
    if not memory_blocks:
        return
    existing = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance_id)
    existing_by_type = {b.memory_type: b for b in existing}
    for mem_type, content in memory_blocks.items():
        if not content:
            continue
        if mem_type in existing_by_type:
            await MemoryBlockDAO.update(
                MemoryBlockUpdate(id=existing_by_type[mem_type].id, content=content)
            )
        else:
            await MemoryBlockDAO.create(
                MemoryBlockCreate(
                    agent_instance_id=agent_instance_id,
                    memory_type=mem_type,
                    content=content,
                )
            )
```

- [ ] **Step 6: Update `_agents_create` to accept `endpointGroupId` and `memoryBlocks`**

Replace the existing `_agents_create` function body (lines 116–169) with:

```python
async def _agents_create(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()

    agent_type_id = UUID(body["agentTypeId"])
    existing_type = await AgentTypeDAO.get_by_id(agent_type_id)
    if existing_type is None or existing_type.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_type_not_found"}),
            content_type="application/json",
        )

    raw_endpoint_group_id = body.get("endpointGroupId")
    endpoint_group_id = UUID(raw_endpoint_group_id) if raw_endpoint_group_id else None

    uuid_value = uuid4()

    agent = await AgentInstanceDAO.create(
        AgentInstanceCreate(
            agent_type_id=agent_type_id,
            user_id=auth_context["user_id"],
            name=body.get("name"),
            agent_id=f"agent-{uuid_value}",
            phone_no=body.get("phoneNo"),
            whatsapp_key=body.get("whatsappKey"),
            is_sub_agent=body.get("isSubAgent", False),
            is_active=body.get("isActive", True),
            status=body.get("status", "idle"),
            endpoint_group_id=endpoint_group_id,
        )
    )

    await CollaborationSessionDAO.create(
        CollaborationSessionCreate(
            user_id=auth_context["user_id"],
            main_agent_id=agent.id,
            session_id=f"default-{uuid_value}",
            name=_("預設對話"),
            status=CollaborationStatus.active,
        )
    )

    await CollaborationSessionDAO.create(
        CollaborationSessionCreate(
            user_id=auth_context["user_id"],
            main_agent_id=agent.id,
            session_id=f"ghost-{uuid_value}",
            name=_("心靈對話"),
            status=CollaborationStatus.active,
        )
    )

    await _upsert_memory_blocks(agent.id, body.get("memoryBlocks") or {})

    return web.json_response({"agent": _serialize_agent_instance(agent)}, status=201)
```

- [ ] **Step 7: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_api_app.py::test_agents_create_accepts_endpoint_group_and_memory_blocks -v
```

Expected: PASS.

- [ ] **Step 8: Run full unit suite**

```bash
python -m pytest tests/unit/test_api_app.py -v
```

Expected: all tests PASS.

- [ ] **Step 9: Add `endpointGroupId` to `DashboardDataProvider._get_agents`**

`GET /api/dashboard/agents` is the list used to populate the agent cards. Without `endpointGroupId` here, the edit form pre-fill will always be blank.

In `src/api/dashboard.py`, inside `_get_agents`, add `"endpointGroupId"` to the dict built for each row:

```python
agents.append(
    {
        "id": str(row.id),
        "name": _agent_display_name(row),
        "role": "主控與協調" if not row.is_sub_agent else "協作子代理",
        "status": _map_agent_status(row.status),
        "currentTask": "等待後端聚合輸出",
        "latestOutput": "最近輸出會在後續版本接入真實聚合。",
        "scheduled": row.status != "offline",
        "isActive": row.is_active,
        "isSubAgent": row.is_sub_agent,
        "phoneNo": row.phone_no,
        "whatsappKey": row.whatsapp_key,
        "agentTypeId": type_id,
        "agentTypeName": type_name_lookup.get(type_id),
        "endpointGroupId": str(row.endpoint_group_id) if row.endpoint_group_id else None,
    }
)
```

- [ ] **Step 10: Commit**

```bash
git add src/api/app.py src/api/dashboard.py tests/unit/test_api_app.py
git commit -m "feat: accept endpointGroupId and memoryBlocks in agents create endpoint"
```

---

## Task 4: Backend — add `_agents_update` and `_agents_get_memory_blocks`

**Files:**
- Modify: `src/api/app.py`
- Test: `tests/unit/test_api_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_api_app.py`:

```python
@pytest.mark.asyncio
async def test_agents_update_upserts_fields_and_memory_blocks(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()
    group_id = uuid4()

    fake_agent_before = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "name": "Old Name",
            "agent_type_id": uuid4(),
            "status": "idle",
            "phone_no": None,
            "whatsapp_key": None,
            "is_sub_agent": False,
            "is_active": True,
            "agent_id": "agent-001",
            "endpoint_group_id": None,
            "created_at": None,
        },
    )()
    fake_agent_after = type(
        "Agent",
        (),
        {
            "id": agent_instance_id,
            "user_id": user_id,
            "name": "New Name",
            "agent_type_id": uuid4(),
            "status": "idle",
            "phone_no": None,
            "whatsapp_key": None,
            "is_sub_agent": False,
            "is_active": True,
            "agent_id": "agent-001",
            "endpoint_group_id": group_id,
            "created_at": None,
        },
    )()
    fake_block = type(
        "Block",
        (),
        {"id": uuid4(), "memory_type": "SOUL", "content": "old soul"},
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent_before)
    )
    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.update", AsyncMock(return_value=fake_agent_after)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id",
        AsyncMock(return_value=[fake_block]),
    )
    update_mock = AsyncMock(return_value=fake_block)
    monkeypatch.setattr("api.app.MemoryBlockDAO.update", update_mock)
    monkeypatch.setattr("api.app.MemoryBlockDAO.create", AsyncMock(return_value=fake_block))

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.patch(
            f"/api/dashboard/agents/{agent_instance_id}",
            headers={"X-API-Key": "good-key"},
            json={
                "name": "New Name",
                "endpointGroupId": str(group_id),
                "memoryBlocks": {"SOUL": "new soul content"},
            },
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["agent"]["name"] == "New Name"
    assert payload["agent"]["endpointGroupId"] == str(group_id)
    # SOUL existed → update called, not create
    update_mock.assert_called_once()


@pytest.mark.asyncio
async def test_agents_get_memory_blocks_returns_typed_dict(monkeypatch) -> None:
    user_id = uuid4()
    agent_instance_id = uuid4()

    fake_agent = type(
        "Agent",
        (),
        {"id": agent_instance_id, "user_id": user_id},
    )()
    soul_block = type(
        "Block", (), {"memory_type": "SOUL", "content": "我是助手"}
    )()
    profile_block = type(
        "Block", (), {"memory_type": "USER_PROFILE", "content": "用戶喜歡簡短回答"}
    )()

    monkeypatch.setattr(
        "api.app.AgentInstanceDAO.get_by_id", AsyncMock(return_value=fake_agent)
    )
    monkeypatch.setattr(
        "api.app.MemoryBlockDAO.get_by_agent_instance_id",
        AsyncMock(return_value=[soul_block, profile_block]),
    )

    app = create_app(
        _FakeQueue(),
        _FakeDedup(),
        dashboard_data_provider=_FakeDashboardProvider(),
        auth_service=_FakeAuthService(user_id),
    )
    server = TestServer(app)
    client = TestClient(server)

    await client.start_server()
    try:
        response = await client.get(
            f"/api/dashboard/agents/{agent_instance_id}/memory-blocks",
            headers={"X-API-Key": "good-key"},
        )
        payload = await response.json()
    finally:
        await client.close()

    assert response.status == 200
    assert payload["SOUL"] == "我是助手"
    assert payload["USER_PROFILE"] == "用戶喜歡簡短回答"
    assert payload["IDENTITY"] == ""  # not present → empty string
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_api_app.py::test_agents_update_upserts_fields_and_memory_blocks tests/unit/test_api_app.py::test_agents_get_memory_blocks_returns_typed_dict -v
```

Expected: both FAIL (routes not registered yet).

- [ ] **Step 3: Add `_agents_update` handler**

Add after `_agents_create` in `src/api/app.py`:

```python
async def _agents_update(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_instance_id = UUID(request.match_info["agent_id"])
    body = await request.json()

    existing = await AgentInstanceDAO.get_by_id(agent_instance_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    raw_endpoint_group_id = body.get("endpointGroupId")
    endpoint_group_id = UUID(raw_endpoint_group_id) if raw_endpoint_group_id else None

    update_kwargs: dict = {"id": agent_instance_id}
    if "name" in body:
        update_kwargs["name"] = body["name"]
    if "phoneNo" in body:
        update_kwargs["phone_no"] = body["phoneNo"]
    if "whatsappKey" in body:
        update_kwargs["whatsapp_key"] = body["whatsappKey"]
    if "isSubAgent" in body:
        update_kwargs["is_sub_agent"] = body["isSubAgent"]
    if "isActive" in body:
        update_kwargs["is_active"] = body["isActive"]
    if raw_endpoint_group_id is not None:
        update_kwargs["endpoint_group_id"] = endpoint_group_id

    updated = await AgentInstanceDAO.update(AgentInstanceUpdate(**update_kwargs))
    if updated is None:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    await _upsert_memory_blocks(agent_instance_id, body.get("memoryBlocks") or {})

    return web.json_response({"agent": _serialize_agent_instance(updated)})
```

- [ ] **Step 4: Add `_agents_get_memory_blocks` handler**

Add after `_agents_update` in `src/api/app.py`:

```python
async def _agents_get_memory_blocks(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_instance_id = UUID(request.match_info["agent_id"])

    existing = await AgentInstanceDAO.get_by_id(agent_instance_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    blocks = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance_id)
    result = {"SOUL": "", "USER_PROFILE": "", "IDENTITY": ""}
    for block in blocks:
        if block.memory_type in result:
            result[block.memory_type] = block.content

    return web.json_response(result)
```

- [ ] **Step 5: Register the two new routes**

In the `create_app` function route registration section, add after the existing agents routes:

```python
app.router.add_patch("/api/dashboard/agents/{agent_id}", _agents_update)
app.router.add_get("/api/dashboard/agents/{agent_id}/memory-blocks", _agents_get_memory_blocks)
```

These must be added **before** the `/api/dashboard/agents/{agent_id}/tools/{tool_id}` route to avoid path conflicts.

- [ ] **Step 6: Run the new tests**

```bash
python -m pytest tests/unit/test_api_app.py::test_agents_update_upserts_fields_and_memory_blocks tests/unit/test_api_app.py::test_agents_get_memory_blocks_returns_typed_dict -v
```

Expected: both PASS.

- [ ] **Step 7: Run full unit suite**

```bash
python -m pytest tests/unit/test_api_app.py -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/api/app.py tests/unit/test_api_app.py
git commit -m "feat: add PATCH agents update and GET agents memory-blocks endpoints"
```

---

## Task 5: Frontend types

**Files:**
- Modify: `frontend/src/types/dashboard.ts`

- [ ] **Step 1: Add `MemoryBlocksInput` type**

In `frontend/src/types/dashboard.ts`, add after the `AgentUpdateBody` interface:

```ts
export interface MemoryBlocksInput {
  SOUL?: string;
  USER_PROFILE?: string;
  IDENTITY?: string;
}
```

- [ ] **Step 2: Add `endpointGroupId` to `AgentCardData`**

In the `AgentCardData` interface, add after `agentTypeName`:

```ts
  endpointGroupId: string | null;
```

- [ ] **Step 3: Extend `AgentCreateBody` and `AgentUpdateBody`**

In `AgentCreateBody`, add:

```ts
  endpointGroupId?: string;
  memoryBlocks?: MemoryBlocksInput;
```

In `AgentUpdateBody`, add:

```ts
  endpointGroupId?: string;
  memoryBlocks?: MemoryBlocksInput;
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors (or only pre-existing errors unrelated to these types).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/dashboard.ts
git commit -m "feat: add MemoryBlocksInput type and extend agent create/update body types"
```

---

## Task 6: Frontend API function

**Files:**
- Modify: `frontend/src/api/dashboard.ts`

- [ ] **Step 1: Add `fetchAgentMemoryBlocks`**

In `frontend/src/api/dashboard.ts`, add after `fetchAgentTools`:

```ts
export function fetchAgentMemoryBlocks(id: string): Promise<MemoryBlocksInput> {
  return requestJson<MemoryBlocksInput>(`/api/dashboard/agents/${id}/memory-blocks`);
}
```

Also add `MemoryBlocksInput` to the import at the top of the file:

```ts
import {
  AgentCardData,
  AgentCreateBody,
  AgentToolUpdatePayload,
  AgentToolsPayload,
  AgentTypeItem,
  AgentTypesPayload,
  AgentUpdateBody,
  AgentsPayload,
  MemoryBlocksInput,
  MemoryPayload,
  OverviewPayload,
  SettingsPayload,
  TasksPayload,
  UsagePayload,
} from "../types/dashboard";
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/dashboard.ts
git commit -m "feat: add fetchAgentMemoryBlocks API function"
```

---

## Task 7: Frontend — extend AgentTab with dropdown + memory block text areas

**Files:**
- Modify: `frontend/src/components/agents/AgentTab.tsx`

- [ ] **Step 1: Update imports**

At the top of `frontend/src/components/agents/AgentTab.tsx`, update the imports:

```ts
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  createAgent,
  fetchAgentMemoryBlocks,
  fetchAgents,
  fetchAgentTypes,
  fetchSettings,
  updateAgent,
} from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { agentTypesPayload } from "../../mock/dashboard";
import type {
  AgentCardData,
  AgentTypeItem,
  AgentsPayload,
  SettingsPayload,
} from "../../types/dashboard";
```

- [ ] **Step 2: Update `FormState` interface and `EMPTY_FORM`**

Replace the existing `FormState` interface and `EMPTY_FORM` constant:

```ts
interface FormState {
  name: string;
  agentTypeId: string;
  phoneNo: string;
  whatsappKey: string;
  isActive: boolean;
  isSubAgent: boolean;
  endpointGroupId: string;
  soul: string;
  userProfile: string;
  identity: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  agentTypeId: "",
  phoneNo: "",
  whatsappKey: "",
  isActive: true,
  isSubAgent: false,
  endpointGroupId: "",
  soul: "",
  userProfile: "",
  identity: "",
};
```

- [ ] **Step 3: Add settings state and memory loading flag**

Inside the `AgentTab` component, after the existing `const [saving, setSaving] = useState(false);` line, add:

```ts
const [memoryLoading, setMemoryLoading] = useState(false);

const { resource: settingsResource } = useDashboardResource(
  fetchSettings,
  { locales: [], featureFlags: {}, endpoints: [], groups: [], authKeys: [], source: "mock" } as SettingsPayload,
  {},
);
const [endpointGroups, setEndpointGroups] = useState<SettingsPayload["groups"]>([]);
```

- [ ] **Step 4: Sync endpoint groups from settings**

After the existing `useEffect` that syncs `agentTypes`, add:

```ts
useEffect(() => {
  setEndpointGroups(settingsResource.groups);
}, [settingsResource]);
```

- [ ] **Step 5: Update `openEdit` to fetch memory blocks**

Replace the existing `openEdit` function:

```ts
function openEdit(item: AgentCardData) {
  setEditing(item);
  setForm({
    name: item.name,
    agentTypeId: item.agentTypeId ?? "",
    phoneNo: item.phoneNo ?? "",
    whatsappKey: item.whatsappKey ?? "",
    isActive: item.isActive,
    isSubAgent: item.isSubAgent,
    endpointGroupId: item.endpointGroupId ?? "",
    soul: "",
    userProfile: "",
    identity: "",
  });
  setFormError(null);
  setShowForm(true);
  setMemoryLoading(true);
  fetchAgentMemoryBlocks(item.id)
    .then((blocks) => {
      setForm((f) => ({
        ...f,
        soul: blocks.SOUL ?? "",
        userProfile: blocks.USER_PROFILE ?? "",
        identity: blocks.IDENTITY ?? "",
      }));
    })
    .catch(() => {
      // non-fatal — leave fields empty
    })
    .finally(() => {
      setMemoryLoading(false);
    });
}
```

- [ ] **Step 6: Update `handleSave` to include new fields**

Replace the `createAgent` and `updateAgent` call blocks inside `handleSave`:

```ts
if (editing) {
  const result = await updateAgent(editing.id, {
    name: form.name.trim(),
    agentTypeId: form.agentTypeId,
    phoneNo: form.phoneNo.trim() || undefined,
    whatsappKey: form.whatsappKey.trim() || undefined,
    isActive: form.isActive,
    isSubAgent: form.isSubAgent,
    endpointGroupId: form.endpointGroupId || undefined,
    memoryBlocks: {
      SOUL: form.soul || undefined,
      USER_PROFILE: form.userProfile || undefined,
      IDENTITY: form.identity || undefined,
    },
  });
  setItems((prev) => prev.map((i) => (i.id === editing.id ? result.agent : i)));
} else {
  const result = await createAgent({
    name: form.name.trim(),
    agentTypeId: form.agentTypeId,
    phoneNo: form.phoneNo.trim() || undefined,
    whatsappKey: form.whatsappKey.trim() || undefined,
    isActive: form.isActive,
    isSubAgent: form.isSubAgent,
    endpointGroupId: form.endpointGroupId || undefined,
    memoryBlocks: {
      SOUL: form.soul || undefined,
      USER_PROFILE: form.userProfile || undefined,
      IDENTITY: form.identity || undefined,
    },
  });
  setItems((prev) => [...prev, result.agent]);
}
```

- [ ] **Step 7: Add LLM Endpoint Group dropdown to modal**

In the modal JSX, after the Agent Type `<label>` block (after line ~219) and before the Phone No `<label>`, add:

```tsx
<label>
  LLM Endpoint Group
  <select
    value={form.endpointGroupId}
    onChange={(e) => setForm((f) => ({ ...f, endpointGroupId: e.target.value }))}
  >
    <option value="">（不指定）</option>
    {endpointGroups.map((g) => (
      <option key={g.id} value={g.id}>
        {g.name}
      </option>
    ))}
  </select>
</label>
```

- [ ] **Step 8: Add Memory Blocks text areas to modal**

After the WhatsApp Key `<label>` block and before the `isActive` checkbox, add:

```tsx
<fieldset style={{ border: "none", padding: 0, margin: "0.5rem 0" }}>
  <legend style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Memory Blocks</legend>

  <label>
    SOUL
    <textarea
      rows={4}
      value={form.soul}
      disabled={memoryLoading}
      placeholder={memoryLoading ? "載入中…" : "人格、價值觀、語氣偏好、行為準則"}
      onChange={(e) => setForm((f) => ({ ...f, soul: e.target.value }))}
    />
  </label>

  <label>
    USER_PROFILE
    <textarea
      rows={4}
      value={form.userProfile}
      disabled={memoryLoading}
      placeholder={memoryLoading ? "載入中…" : "使用者偏好、背景、習慣、長期需求"}
      onChange={(e) => setForm((f) => ({ ...f, userProfile: e.target.value }))}
    />
  </label>

  <label>
    IDENTITY
    <textarea
      rows={4}
      value={form.identity}
      disabled={memoryLoading}
      placeholder={memoryLoading ? "載入中…" : "Agent 身份標記"}
      onChange={(e) => setForm((f) => ({ ...f, identity: e.target.value }))}
    />
  </label>
</fieldset>
```

- [ ] **Step 9: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 10: Run the full backend unit test suite to confirm no regressions**

```bash
cd .. && source .venv/bin/activate && python -m pytest tests/unit/ -v
```

Expected: all tests PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/agents/AgentTab.tsx
git commit -m "feat: add LLM Endpoint Group dropdown and SOUL/USER_PROFILE/IDENTITY memory block text areas to agent add/edit modal"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
source .venv/bin/activate
python -m pytest tests/unit/ -v
```

Expected: all tests PASS including the 4 new ones in `test_api_app.py`.

- [ ] **TypeScript final check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.
