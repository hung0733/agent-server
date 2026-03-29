# Dashboard Tasks and Memory Enrichment Design

## Context

The dashboard already supports API-key login, user-scoped overview access, and blocking first-load behavior. Recent uncommitted work adds logout, login failure feedback, and conservative user scoping for tasks and memory data.

The remaining gap is that the `tasks` and `memory` pages still expose thin payloads:

- `tasks` is mostly a queue-status list with limited context.
- `memory` is a single title/body summary with no structure for recent activity.

This design strengthens both views while staying conservative:

- keep existing API routes
- reuse current DAO access patterns
- avoid schema changes
- avoid showing cross-user or weakly-attributed data

## Goals

- Enrich the `tasks` timeline using existing queue, schedule, and message data.
- Enrich the `memory` payload with structured summaries and recent entries.
- Preserve strict user scoping using the authenticated user's agent set.
- Keep the frontend resilient to partially-missing fields.
- Prefer real-first empty states over misleading mock activity.

## Non-Goals

- No database schema changes.
- No new authentication model.
- No attempt to infer business semantics that are not reliably derivable from current records.
- No major page redesign beyond what is needed to present richer structured data.

## Recommended Approach

Use the existing `DashboardDataProvider` as the aggregation boundary and extend the `tasks` and `memory` payloads in a backward-compatible way.

Why this approach:

- it keeps backend changes localized to the current dashboard assembly layer
- it fits the existing mixed-real-data pattern already used by the dashboard
- it avoids introducing a premature service split for data that is still evolving
- it allows frontend rendering upgrades without rewriting route contracts

## Architecture

### Backend aggregation boundary

`src/api/dashboard.py` remains the single point that shapes dashboard payloads for frontend use.

The provider will:

- resolve the current user's agent IDs once per request path
- fetch candidate task rows, schedules, and messages
- filter each source to records confidently attributable to those agent IDs
- assemble richer response objects with consistent status mapping and timestamps

### Frontend rendering boundary

The frontend continues to consume `/api/dashboard/tasks` and `/api/dashboard/memory`.

Changes stay within:

- `frontend/src/types/dashboard.ts`
- `frontend/src/components/tasks/TaskTimeline.tsx`
- `frontend/src/pages/TasksPage.tsx`
- `frontend/src/pages/MemoryPage.tsx`
- any small supporting UI components or tests needed to render new optional fields

The first-load blocking behavior remains unchanged.

## Tasks Payload Design

### Response shape

Keep the top-level payload stable:

```ts
interface TasksPayload {
  items: TimelineItem[];
  source: string;
}
```

Extend each timeline item with optional context fields:

```ts
interface TimelineItem {
  id: string;
  type: string;
  sourceAgent: string;
  targetAgent: string;
  title: string;
  summary: string;
  timestamp: string;
  status: "healthy" | "warning" | "danger" | "idle";
  technicalDetails: string;
  group?: "queue" | "schedule" | "message";
  origin?: string;
  relatedTaskId?: string;
  scheduleLabel?: string;
  messageSnippet?: string;
}
```

Existing fields remain present so current consumers do not break.

### Event sourcing rules

The timeline is assembled from three conservative sources.

#### Queue events

Queue rows remain the backbone of the timeline.

- include only rows whose `claimed_by` belongs to the user's agent set
- map queue status into existing dashboard tones
- expose `task_id` as technical detail and `relatedTaskId` when available
- create human-readable titles and summaries from status and error context

#### Schedule context

Schedules add timeline events only when they can be tied to a user-owned agent.

- if schedule records expose an agent reference that matches the user's agent set, create schedule-flavored timeline items
- use schedule data to enrich queue items when a direct event is too weak to stand alone
- if schedule-to-agent attribution is unreliable in current records, skip standalone schedule events entirely

This keeps schedule data additive rather than speculative.

#### Message events

Recent agent messages can become timeline items when:

- `sender_agent_id` or `receiver_agent_id` belongs to the user's agent set
- the message has enough content to summarize safely

Message-derived events are intended to show recent coordination or handoff activity, not full conversation transcripts.

### Ordering and limits

- merge all candidate events into one list
- normalize timestamps
- sort newest first
- cap the returned list to a small dashboard-safe size
- return `items: []` when there are no attributable events

No fallback mock event will be emitted for the tasks page after this change.

## Memory Payload Design

### Response shape

Preserve the current fields and add structured sections:

```ts
interface MemoryPayload {
  title: string;
  body: string;
  source: string;
  stats?: {
    totalEntries: number;
    activeAgents: number;
    lastUpdatedAt: string | null;
  };
  health?: {
    status: "healthy" | "warning" | "danger" | "idle";
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

### Aggregation rules

`memory` continues to use recent messages as its only real data source.

- fetch recent messages
- filter to messages where sender or receiver belongs to the user's agent set
- derive a short dashboard-safe summary from `content_json`
- compute counts and latest timestamp from the filtered set

The top-level `title` and `body` should become concise executive summaries based on the filtered set, for example:

- title: recent memory activity count or stable/idle state
- body: short explanation of the latest meaningful write pattern

### Safe summarization

Recent entry summaries should prefer:

- `content_json.text`
- `content_json.summary`
- short serialized content fallback when the structure is unknown

The backend must keep summaries short and avoid dumping raw large payloads into the dashboard.

### Health rules

Use simple, conservative health logic:

- `healthy`: recent user-scoped memory activity exists
- `idle`: no recent records but this is not an error condition
- `warning`: records exist but appear stale relative to the current time window
- `danger`: reserve only for clear processing failure indicators already present in source data

Do not invent failure states from missing information alone.

## Frontend Presentation

### Tasks page

The tasks page remains a timeline, but each card becomes more informative.

- show source/target agents prominently
- show a badge or small label for `group` such as queue, schedule, or message
- keep timestamp visible in the card header
- keep technical details inside the existing collapsible details area
- treat missing optional fields as absent context, not as an error

If `items` is empty, show a deliberate empty state that explains there is no recent user-scoped task activity.

### Memory page

Replace the single empty-state-style rendering with a structured layout:

- top summary card using `title`, `body`, and `health`
- compact stats row for entry count, active agent count, and last update time
- recent entries list for the latest memory-like items

If there are no `recentEntries`, render the summary card plus an explicit empty state instead of fake content.

## Error Handling

- DAO failures continue to degrade gracefully to empty collections
- missing optional fields do not fail the response
- malformed message content falls back to short string serialization
- unauthorized behavior remains unchanged and continues to be handled by existing API-key logic

## Testing Strategy

### Backend

Add or expand provider unit tests to cover:

- task rows filtered to user-owned agents only
- message-derived timeline items filtered to user-owned agents only
- combined timeline ordering by timestamp
- memory stats and recent entries derived only from user-scoped messages
- empty payload behavior when no attributable rows exist

### Frontend

Add or expand tests to cover:

- task timeline rendering with optional context fields present and absent
- memory page rendering of summary, stats, and recent entries
- empty-state rendering when structured sections are empty

### Verification

Run:

- `source .venv/bin/activate && python -m pytest tests/test_schema_guard.py -v`
- `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_provider.py -v`
- other affected backend unit tests as needed
- `npm test`
- `npm run build`

## Risks and Mitigations

- Risk: schedule attribution may be too weak in current DAO records.
  - Mitigation: keep schedule enrichment optional and skip standalone events unless attribution is reliable.
- Risk: message content may be noisy or oversized.
  - Mitigation: summarize conservatively and cap dashboard text.
- Risk: frontend and backend drift on optional fields.
  - Mitigation: add types and tests for missing-field tolerance.

## Implementation Notes

- Keep code changes incremental and local.
- Prefer helper functions inside `src/api/dashboard.py` before introducing new modules.
- Preserve existing route names and response top-level keys.
- Do not commit unrelated workspace changes while implementing this design.
