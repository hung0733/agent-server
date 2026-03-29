# Dashboard Tasks and Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the dashboard `tasks` and `memory` pages with conservative, user-scoped real data while preserving existing routes and graceful empty states.

**Architecture:** Keep `src/api/dashboard.py` as the backend aggregation boundary and extend its payloads in a backward-compatible way. Update frontend types and page components to render richer optional fields, then verify both backend scoping and frontend fallbacks with focused tests.

**Tech Stack:** Python 3.12, aiohttp, pytest, React 18, TypeScript, Vitest, Testing Library

---

## File Map

- Modify: `src/api/dashboard.py`
  - Extend task timeline assembly and memory aggregation.
- Modify: `tests/unit/test_dashboard_provider.py`
  - Add backend coverage for ordering, user scoping, and empty states.
- Modify: `frontend/src/types/dashboard.ts`
  - Add optional structured fields for tasks and memory payloads.
- Modify: `frontend/src/mock/dashboard.ts`
  - Keep mock data aligned with the expanded frontend contract.
- Modify: `frontend/src/components/tasks/TaskTimeline.tsx`
  - Render group/context metadata and empty-state-safe cards.
- Modify: `frontend/src/components/tasks/__tests__/TaskTimeline.test.tsx`
  - Cover optional task context rendering.
- Modify: `frontend/src/pages/MemoryPage.tsx`
  - Replace single empty state with summary, stats, and recent entries layout.
- Create: `frontend/src/pages/__tests__/MemoryPage.test.tsx`
  - Verify structured memory rendering and empty handling.

### Task 1: Expand backend provider tests first

**Files:**
- Modify: `tests/unit/test_dashboard_provider.py`
- Test: `tests/unit/test_dashboard_provider.py`

- [ ] **Step 1: Write the failing backend tests for richer tasks and memory payloads**

```python
@pytest.mark.asyncio
async def test_get_tasks_merges_user_scoped_queue_and_message_events_sorted_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_agent_id = uuid4()
    now = datetime.now(UTC)

    async def fake_get_by_user_id(user_id, limit=100):
        return [SimpleNamespace(id=user_agent_id, name="main")]

    async def fake_task_get_all(limit=8):
        return [
            SimpleNamespace(
                id=uuid4(),
                status="running",
                claimed_by=user_agent_id,
                error_message=None,
                queued_at=now,
                task_id=uuid4(),
            )
        ]

    async def fake_message_get_all(limit=20):
        return [
            SimpleNamespace(
                id=uuid4(),
                sender_agent_id=user_agent_id,
                receiver_agent_id=None,
                content_json={"text": "latest handoff"},
                created_at=now.replace(microsecond=0),
            )
        ]

    monkeypatch.setattr("api.dashboard.AgentInstanceDAO.get_by_user_id", fake_get_by_user_id)
    monkeypatch.setattr("api.dashboard.TaskQueueDAO.get_all", fake_task_get_all)
    monkeypatch.setattr("api.dashboard.AgentMessageDAO.get_all", fake_message_get_all)

    provider = DashboardDataProvider(_FakeQueue(), _FakeDedup())
    payload = await provider.get_tasks(user_id=uuid4())

    assert payload["items"][0]["group"] == "message"
    assert payload["items"][1]["group"] == "queue"
    assert payload["items"][0]["messageSnippet"] == "latest handoff"


@pytest.mark.asyncio
async def test_get_tasks_returns_empty_items_when_no_user_scoped_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_user_id(user_id, limit=100):
        return []

    async def fake_task_get_all(limit=8):
        return []

    async def fake_message_get_all(limit=20):
        return []

    monkeypatch.setattr("api.dashboard.AgentInstanceDAO.get_by_user_id", fake_get_by_user_id)
    monkeypatch.setattr("api.dashboard.TaskQueueDAO.get_all", fake_task_get_all)
    monkeypatch.setattr("api.dashboard.AgentMessageDAO.get_all", fake_message_get_all)

    provider = DashboardDataProvider(_FakeQueue(), _FakeDedup())
    payload = await provider.get_tasks(user_id=uuid4())

    assert payload == {"items": [], "source": "mixed"}


@pytest.mark.asyncio
async def test_get_memory_returns_structured_user_scoped_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    user_agent_id = uuid4()
    now = datetime.now(UTC)

    async def fake_get_by_user_id(user_id, limit=100):
        return [SimpleNamespace(id=user_agent_id, name="main")]

    async def fake_get_all(limit=20):
        return [
            SimpleNamespace(
                id=uuid4(),
                sender_agent_id=user_agent_id,
                receiver_agent_id=None,
                content_json={"text": "memory summary"},
                created_at=now,
            )
        ]

    monkeypatch.setattr("api.dashboard.AgentInstanceDAO.get_by_user_id", fake_get_by_user_id)
    monkeypatch.setattr("api.dashboard.AgentMessageDAO.get_all", fake_get_all)

    provider = DashboardDataProvider(_FakeQueue(), _FakeDedup())
    payload = await provider.get_memory(user_id=uuid4())

    assert payload["stats"]["totalEntries"] == 1
    assert payload["stats"]["activeAgents"] == 1
    assert payload["recentEntries"][0]["summary"] == "memory summary"
    assert payload["health"]["status"] == "healthy"
```

- [ ] **Step 2: Run the provider tests to verify the new expectations fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_provider.py -v`
Expected: FAIL because `get_tasks()` still emits only queue items or mock fallback, and `get_memory()` still returns only `title` and `body`.

- [ ] **Step 3: Implement the minimal backend helpers in `src/api/dashboard.py`**

```python
def _safe_message_text(content: Any) -> str:
    if isinstance(content, dict):
        text = content.get("text") or content.get("summary")
        if text:
            return str(text)[:160]
        return str(content)[:160]
    return str(content)[:160]


def _agent_name_lookup(rows: list[Any]) -> dict[Any, str]:
    return {row.id: (row.name or row.agent_id or f"agent-{str(row.id)[:8]}") for row in rows}


async def _get_user_agent_map(self, user_id=None) -> dict[Any, str]:
    rows = await self._get_user_agents(user_id=user_id, limit=100)
    return _agent_name_lookup(rows)
```

- [ ] **Step 4: Extend `get_tasks()` to merge queue and message events and return empty when no activity exists**

```python
async def get_tasks(self, user_id=None) -> dict[str, Any]:
    user_agents = await self._get_user_agent_map(user_id)
    user_agent_ids = set(user_agents)
    task_rows = await self._get_task_rows(limit=8, user_agent_ids=user_agent_ids)
    messages = await self._get_recent_messages(limit=12, user_agent_ids=user_agent_ids)

    items: list[dict[str, Any]] = []

    for task in task_rows:
        items.append(
            {
                "id": str(task.id),
                "type": task.status,
                "sourceAgent": user_agents.get(task.claimed_by, str(task.claimed_by or "system")),
                "targetAgent": "queue",
                "title": f"任務 {task.status}",
                "summary": task.error_message or "系統任務狀態已同步。",
                "timestamp": task.queued_at.isoformat() if task.queued_at else _iso_now(),
                "status": _map_task_status(task.status),
                "technicalDetails": str(task.task_id),
                "group": "queue",
                "origin": "task_queue",
                "relatedTaskId": str(task.task_id),
            }
        )

    for message in messages[:4]:
        items.append(
            {
                "id": f"msg-{message.id}",
                "type": "message",
                "sourceAgent": user_agents.get(message.sender_agent_id, "system"),
                "targetAgent": user_agents.get(message.receiver_agent_id, "inbox"),
                "title": "最近協作互動",
                "summary": _safe_message_text(message.content_json),
                "timestamp": message.created_at.isoformat() if message.created_at else _iso_now(),
                "status": "healthy",
                "technicalDetails": str(message.id),
                "group": "message",
                "origin": "agent_message",
                "messageSnippet": _safe_message_text(message.content_json),
            }
        )

    items.sort(key=lambda item: item["timestamp"], reverse=True)
    return {"items": items[:8], "source": "mixed"}
```

- [ ] **Step 5: Extend `get_memory()` to emit structured stats, health, and recent entries**

```python
async def get_memory(self, user_id=None) -> dict[str, Any]:
    user_agents = await self._get_user_agent_map(user_id)
    user_agent_ids = set(user_agents)
    messages = await self._get_recent_messages(limit=20, user_agent_ids=user_agent_ids)

    if not messages:
        return {
            "title": "最近記憶活動較少",
            "body": "暫時未見屬於你的 agent 記憶寫入。",
            "stats": {"totalEntries": 0, "activeAgents": 0, "lastUpdatedAt": None},
            "health": {"status": "idle", "note": "目前沒有可顯示的 user-scoped 記錄。"},
            "recentEntries": [],
            "source": "mixed",
        }

    latest = messages[0]
    active_agents = {
        agent_id
        for message in messages
        for agent_id in (message.sender_agent_id, message.receiver_agent_id)
        if agent_id in user_agent_ids
    }
    recent_entries = [
        {
            "id": str(message.id),
            "agentName": user_agents.get(message.sender_agent_id) or user_agents.get(message.receiver_agent_id, "system"),
            "timestamp": message.created_at.isoformat() if message.created_at else _iso_now(),
            "summary": _safe_message_text(message.content_json),
        }
        for message in messages[:5]
    ]

    return {
        "title": f"最近有 {len(messages)} 條 user-scoped 記錄",
        "body": _safe_message_text(latest.content_json),
        "stats": {
            "totalEntries": len(messages),
            "activeAgents": len(active_agents),
            "lastUpdatedAt": latest.created_at.isoformat() if latest.created_at else None,
        },
        "health": {"status": "healthy", "note": "最近仍有記憶寫入與整理活動。"},
        "recentEntries": recent_entries,
        "source": "mixed",
    }
```

- [ ] **Step 6: Run the provider tests again and make them pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_provider.py -v`
Expected: PASS for the new task and memory coverage.

- [ ] **Step 7: Commit the backend provider enrichment**

```bash
git add src/api/dashboard.py tests/unit/test_dashboard_provider.py
git commit -m "Enrich dashboard task and memory payloads"
```

### Task 2: Update frontend contracts and task timeline rendering

**Files:**
- Modify: `frontend/src/types/dashboard.ts`
- Modify: `frontend/src/mock/dashboard.ts`
- Modify: `frontend/src/components/tasks/TaskTimeline.tsx`
- Modify: `frontend/src/components/tasks/__tests__/TaskTimeline.test.tsx`
- Test: `frontend/src/components/tasks/__tests__/TaskTimeline.test.tsx`

- [ ] **Step 1: Write the failing timeline rendering test for optional task context**

```tsx
it("renders group and message snippet when optional context is present", () => {
  renderWithRouter(
    <TaskTimeline
      items={[
        {
          id: "evt-1",
          type: "message",
          sourceAgent: "Main",
          targetAgent: "Inbox",
          title: "最近協作互動",
          summary: "請回覆最新狀態",
          timestamp: "2026-03-29T10:00:00+08:00",
          status: "healthy",
          technicalDetails: "msg-1",
          group: "message",
          messageSnippet: "請回覆最新狀態",
        },
      ]}
    />,
  );

  expect(screen.getByText("message")).toBeInTheDocument();
  expect(screen.getByText("請回覆最新狀態")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the single timeline test file to verify it fails first**

Run: `cd frontend && npm test -- src/components/tasks/__tests__/TaskTimeline.test.tsx`
Expected: FAIL because the component does not render `group` or `messageSnippet` yet.

- [ ] **Step 3: Extend the TypeScript contracts and mock data**

```ts
export interface TimelineItem {
  id: string;
  type: string;
  sourceAgent: string;
  targetAgent: string;
  title: string;
  summary: string;
  timestamp: string;
  status: SystemStatus;
  technicalDetails: string;
  group?: "queue" | "schedule" | "message";
  origin?: string;
  relatedTaskId?: string;
  scheduleLabel?: string;
  messageSnippet?: string;
}

export interface MemoryPayload {
  title: string;
  body: string;
  source: string;
  stats?: {
    totalEntries: number;
    activeAgents: number;
    lastUpdatedAt: string | null;
  };
  health?: {
    status: SystemStatus;
    note: string;
  };
  recentEntries?: Array<{
    id: string;
    agentName: string;
    timestamp: string;
    summary: string;
  }>;
}
```

- [ ] **Step 4: Render task context without making optional fields required**

```tsx
export default function TaskTimeline({ items }: { items: TimelineItem[] }) {
  const { t } = useTranslation();

  return (
    <div className="timeline">
      {items.map((item) => (
        <article key={item.id} className="card timeline-item">
          <div className="timeline-item__header">
            <div>
              <h3>{item.title}</h3>
              <p>{item.sourceAgent} -&gt; {item.targetAgent}</p>
              {item.group ? <span className="timeline-item__group">{item.group}</span> : null}
            </div>
            <div className="timeline-item__meta">
              <Badge tone={toneMap[item.status]} label={item.timestamp} />
            </div>
          </div>
          <p className="timeline-item__summary">{item.summary}</p>
          {item.messageSnippet && item.messageSnippet !== item.summary ? (
            <p className="timeline-item__snippet">{item.messageSnippet}</p>
          ) : null}
          <details>
            <summary>{t("tasks.technicalDetails")}</summary>
            <p>{item.technicalDetails}</p>
          </details>
        </article>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run the timeline component tests and make them pass**

Run: `cd frontend && npm test -- src/components/tasks/__tests__/TaskTimeline.test.tsx`
Expected: PASS for both the existing source/target test and the new optional-context test.

- [ ] **Step 6: Commit the frontend task timeline contract changes**

```bash
git add frontend/src/types/dashboard.ts frontend/src/mock/dashboard.ts frontend/src/components/tasks/TaskTimeline.tsx frontend/src/components/tasks/__tests__/TaskTimeline.test.tsx
git commit -m "Update dashboard task timeline contracts"
```

### Task 3: Add structured memory page rendering

**Files:**
- Modify: `frontend/src/pages/MemoryPage.tsx`
- Create: `frontend/src/pages/__tests__/MemoryPage.test.tsx`
- Test: `frontend/src/pages/__tests__/MemoryPage.test.tsx`

- [ ] **Step 1: Write the failing memory page test for structured summary rendering**

```tsx
vi.mock("../api/dashboard", () => ({
  fetchMemory: vi.fn().mockResolvedValue({
    title: "最近有 2 條 user-scoped 記錄",
    body: "memory summary",
    source: "mixed",
    stats: {
      totalEntries: 2,
      activeAgents: 1,
      lastUpdatedAt: "2026-03-29T10:00:00+08:00",
    },
    health: {
      status: "healthy",
      note: "最近仍有記憶寫入與整理活動。",
    },
    recentEntries: [
      {
        id: "mem-1",
        agentName: "Main",
        timestamp: "2026-03-29T10:00:00+08:00",
        summary: "memory summary",
      },
    ],
  }),
}));

it("renders summary, stats, and recent entries", async () => {
  renderWithRouter(<MemoryPage />);

  expect(await screen.findByText("最近有 2 條 user-scoped 記錄")).toBeInTheDocument();
  expect(screen.getByText("memory summary")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
  expect(screen.getByText("Main")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the new memory page test to verify it fails**

Run: `cd frontend && npm test -- src/pages/__tests__/MemoryPage.test.tsx`
Expected: FAIL because `MemoryPage` still renders only `EmptyState`.

- [ ] **Step 3: Replace the single empty-state rendering with structured memory sections**

```tsx
export default function MemoryPage() {
  const { t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchMemory, memoryPayload, {
    blockOnFirstLoad: true,
  });

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
      <article className="card">
        <h3>{payload.title || t("memory.emptyTitle")}</h3>
        <p>{payload.body || t("memory.emptyBody")}</p>
        {payload.health ? <p>{payload.health.note}</p> : null}
      </article>

      {payload.stats ? (
        <div className="memory-stats-grid">
          <article className="card"><strong>{payload.stats.totalEntries}</strong><span>Recent entries</span></article>
          <article className="card"><strong>{payload.stats.activeAgents}</strong><span>Active agents</span></article>
          <article className="card"><strong>{payload.stats.lastUpdatedAt ?? "-"}</strong><span>Last updated</span></article>
        </div>
      ) : null}

      {payload.recentEntries?.length ? (
        <div className="memory-entry-list">
          {payload.recentEntries.map((entry) => (
            <article key={entry.id} className="card">
              <h4>{entry.agentName}</h4>
              <p>{entry.summary}</p>
              <span>{entry.timestamp}</span>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title={t("memory.emptyTitle")} body={t("memory.emptyBody")} />
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run the memory page test again and make it pass**

Run: `cd frontend && npm test -- src/pages/__tests__/MemoryPage.test.tsx`
Expected: PASS with the structured sections visible.

- [ ] **Step 5: Commit the structured memory page UI**

```bash
git add frontend/src/pages/MemoryPage.tsx frontend/src/pages/__tests__/MemoryPage.test.tsx
git commit -m "Render structured dashboard memory state"
```

### Task 4: Run integrated verification and reconcile any drift

**Files:**
- Modify: any files from Tasks 1-3 only if verification exposes breakage
- Test: `tests/test_schema_guard.py`
- Test: `tests/unit/test_dashboard_provider.py`
- Test: `frontend/src/components/tasks/__tests__/TaskTimeline.test.tsx`
- Test: `frontend/src/pages/__tests__/MemoryPage.test.tsx`

- [ ] **Step 1: Run backend verification in the project venv**

Run: `source .venv/bin/activate && python -m pytest tests/test_schema_guard.py -v && python -m pytest tests/unit/test_dashboard_provider.py -v && python -m pytest tests/unit/test_api_app.py -v`
Expected: PASS for schema guard, provider tests, and dashboard app contract tests.

- [ ] **Step 2: Run frontend verification for unit tests and production build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS for Vitest suite and Vite production build.

- [ ] **Step 3: If verification reveals drift, make the smallest possible fix in the touched files only**

```python
# Example backend drift fix pattern
if message.created_at and message.created_at.tzinfo is None:
    created_at = message.created_at.replace(tzinfo=UTC)
else:
    created_at = message.created_at
```

```tsx
// Example frontend drift fix pattern
const recentEntries = payload.recentEntries ?? [];
const stats = payload.stats ?? null;
```

- [ ] **Step 4: Re-run only the failing verification commands until all green**

Run: exactly the failed command(s) from Steps 1-2.
Expected: PASS with no remaining regressions.

- [ ] **Step 5: Commit the verified end-to-end enrichment**

```bash
git add src/api/dashboard.py tests/unit/test_dashboard_provider.py frontend/src/types/dashboard.ts frontend/src/mock/dashboard.ts frontend/src/components/tasks/TaskTimeline.tsx frontend/src/components/tasks/__tests__/TaskTimeline.test.tsx frontend/src/pages/MemoryPage.tsx frontend/src/pages/__tests__/MemoryPage.test.tsx
git commit -m "Finalize dashboard task and memory enrichment"
```
