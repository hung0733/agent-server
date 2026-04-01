# Agent Add/Edit: LLM Endpoint Group Dropdown + Memory Blocks

**Date:** 2026-04-02  
**Scope:** Agent create/edit modal — add LLM Endpoint Group dropdown and SOUL / USER_PROFILE / IDENTITY text areas

---

## Problem

The agent add/edit modal (`AgentTab.tsx`) currently has no way to assign an LLM Endpoint Group or set the three core memory blocks (SOUL, USER_PROFILE, IDENTITY). Both fields exist in the backend schema (`endpoint_group_id` FK on `AgentInstance`, `memory_block` table) but are not exposed in the UI or the create/update API routes.

Additionally, `PATCH /api/dashboard/agents/{id}` is referenced in the frontend but not registered in `app.py`, meaning `updateAgent()` currently 404s.

---

## Approach

Inline (Option A): agent create/update API accepts `endpointGroupId` and `memoryBlocks` together. Backend handles upsert atomically. Single API call from frontend.

---

## Backend Changes (`src/api/app.py`)

### 1. Update `_agents_create` (POST `/api/dashboard/agents`)

Accept two new fields in request body:
- `endpointGroupId` (optional UUID string)
- `memoryBlocks` (optional dict: `{ "SOUL": "...", "USER_PROFILE": "...", "IDENTITY": "..." }`)

After creating the `AgentInstance`, iterate `memoryBlocks` and call `MemoryBlockDAO.create()` for each non-empty value.

Pass `endpoint_group_id=UUID(body["endpointGroupId"])` to `AgentInstanceCreate` when provided.

### 2. New `_agents_update` (PATCH `/api/dashboard/agents/{agent_id}`)

- Auth: same `_require_auth` pattern
- Look up agent by `agent_id` path param, verify ownership
- Call `AgentInstanceDAO.update(AgentInstanceUpdate(id=..., **fields))` for agent fields
- Upsert memory blocks: `get_by_agent_instance_id()` → build map by `memory_type` → for each type in body, `update()` if exists, `create()` if not
- Return `{ "agent": _serialize_agent_instance(updated) }`

### 3. New `_agents_get_memory_blocks` (GET `/api/dashboard/agents/{agent_id}/memory-blocks`)

- Fetch all active memory blocks for the agent via `get_by_agent_instance_id()`
- Return `{ "SOUL": "...", "USER_PROFILE": "...", "IDENTITY": "..." }` — missing types return `""`

### 4. Update `_serialize_agent_instance`

Add `"endpointGroupId": str(agent.endpoint_group_id) if agent.endpoint_group_id else None`

### 5. Register new routes

```python
app.router.add_patch("/api/dashboard/agents/{agent_id}", _agents_update)
app.router.add_get("/api/dashboard/agents/{agent_id}/memory-blocks", _agents_get_memory_blocks)
```

---

## Frontend Changes

### `frontend/src/types/dashboard.ts`

```ts
// New type
export interface MemoryBlocksInput {
  SOUL?: string;
  USER_PROFILE?: string;
  IDENTITY?: string;
}

// AgentCardData: add
endpointGroupId: string | null;

// AgentCreateBody: add
endpointGroupId?: string;
memoryBlocks?: MemoryBlocksInput;

// AgentUpdateBody: add
endpointGroupId?: string;
memoryBlocks?: MemoryBlocksInput;
```

### `frontend/src/api/dashboard.ts`

Add one function:
```ts
export function fetchAgentMemoryBlocks(id: string): Promise<MemoryBlocksInput> {
  return requestJson(`/api/dashboard/agents/${id}/memory-blocks`);
}
```

### `frontend/src/components/agents/AgentTab.tsx`

**Form state** — add fields:
```ts
interface FormState {
  // existing...
  endpointGroupId: string;
  soul: string;
  userProfile: string;
  identity: string;
}
```

**Settings fetch** — add `useDashboardResource(fetchSettings, ...)` to get `settings.groups` for the dropdown options.

**`openEdit()`** — after setting form fields, call `fetchAgentMemoryBlocks(item.id)` (async, non-blocking). Show empty strings initially; populate once resolved. Set a `memoryLoading` boolean to show subtle loading state in text areas.

**Modal UI additions** (after existing fields, before checkboxes):

1. **LLM Endpoint Group dropdown**
   ```jsx
   <label>
     LLM Endpoint Group
     <select value={form.endpointGroupId} onChange={...}>
       <option value="">（不指定）</option>
       {endpointGroups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
     </select>
   </label>
   ```

2. **Memory Blocks section** — three `<textarea>` fields with label:
   - SOUL
   - USER_PROFILE
   - IDENTITY

   Each textarea ~4 rows. Disabled with placeholder "載入中…" when `memoryLoading` is true.

**`handleSave()`** — include new fields:
```ts
endpointGroupId: form.endpointGroupId || undefined,
memoryBlocks: {
  SOUL: form.soul || undefined,
  USER_PROFILE: form.userProfile || undefined,
  IDENTITY: form.identity || undefined,
},
```

---

## Data Flow

```
openEdit(item)
  → set form from item (endpointGroupId from item.endpointGroupId)
  → setMemoryLoading(true)
  → fetchAgentMemoryBlocks(item.id)
      → setForm soul/userProfile/identity
      → setMemoryLoading(false)

handleSave() [create]
  → createAgent({ name, agentTypeId, phoneNo, whatsappKey, isActive, isSubAgent,
                  endpointGroupId, memoryBlocks })
  → backend: INSERT AgentInstance + INSERT memory blocks (non-empty only)

handleSave() [edit]
  → updateAgent(id, { same fields })
  → backend: UPDATE AgentInstance + UPSERT memory blocks
```

---

## Files Changed

| File | Change |
|------|--------|
| `src/api/app.py` | Update `_agents_create`, add `_agents_update`, add `_agents_get_memory_blocks`, update `_serialize_agent_instance`, register 2 routes |
| `frontend/src/types/dashboard.ts` | Add `MemoryBlocksInput`, extend `AgentCardData`, `AgentCreateBody`, `AgentUpdateBody` |
| `frontend/src/api/dashboard.ts` | Add `fetchAgentMemoryBlocks` |
| `frontend/src/components/agents/AgentTab.tsx` | Extend form state, fetch settings + memory blocks, add dropdown + 3 text areas |

---

## Out of Scope

- Creating or managing Endpoint Groups themselves (already handled in SettingsPage)
- Memory block versioning or history
- Memory block delete from this UI
