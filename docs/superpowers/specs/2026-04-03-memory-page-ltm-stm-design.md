# Memory Page LTM + STM Refactor Design

**Date**: 2026-04-03
**Status**: Draft - Pending User Review
**Author**: Claude (via brainstorming skill)

## Overview

This design refactors the MemoryPage to display:
1. **Long-Term Memory (LTM)**: Entries from Qdrant vector database
2. **Short-Term Memory (STM)**: Summaries from LangGraph checkpoints (only for current day)

Currently, MemoryPage shows PostgreSQL tasks/messages. This redesign replaces the data source with actual memory entries.

## Requirements Clarification

### From Brainstorming Session

**Q1**: Display scope?
- **Decision**: All agents' memories (user-scoped), default 20 entries, lazy loading at bottom

**Q2**: Entry content?
- **Decision**: Core content + agent name + timestamp (minimal display)

**Q3**: UI Layout?
- **Decision**: Continue using Timeline card style (same as current)

**Q4**: Search functionality?
- **Decision**: Not needed (simplify first version)

**Q5**: LTM + STM display layout?
- **Decision**: Mixed Timeline (STM + LTM entries merged, sorted by timestamp DESC)

**Q6**: STM pagination?
- **Decision**: Show all current-day STM at once (no lazy loading for STM)

**Q7**: STM content display?
- **Decision**: Split summary bullet points, each bullet point = one timeline entry. Show session name + timestamp + session ID. Only query thread_ids that startswith "default-" or "session-"

## Architecture Design

### High-Level Architecture

```
┌─────────────────┐
│  MemoryPage.tsx │
│  (Frontend UI)  │
└─────────────────┘
         │
         ├───────┬──────────────┐
         │       │              │
         ▼       ▼              ▼
    fetchSTM() fetchLTM()  (IntersectionObserver
         │       │            for lazy loading)
         │       │
         ▼       ▼
┌─────────────────┐  ┌──────────────────┐
│ /api/dashboard/ │  │ /api/dashboard/  │
│     stm         │  │      ltm         │
└─────────────────┘  └──────────────────┘
         │                      │
         ▼                      ▼
┌─────────────────┐  ┌──────────────────┐
│ STMDataProvider │  │ LTMDataProvider  │
│  (New Class)    │  │   (New Class)    │
└─────────────────┘  └──────────────────┘
         │                      │
         ▼                      ▼
┌─────────────────┐  ┌──────────────────┐
│ LangGraph       │  │ QdrantVectorStore│
│ checkpoints     │  │ (Existing Class) │
│ (PostgreSQL)    │  │                  │
└─────────────────┘  └──────────────────┘
```

### Data Flow

1. **Frontend**: MemoryPage calls `fetchSTM()` + `fetchLTM()` on mount
2. **STM API**: Queries LangGraph checkpoints, filters current day + thread_id prefix, parses summary bullet points
3. **LTM API**: Queries Qdrant, paginated by timestamp, returns 20 entries per page
4. **Merge**: Frontend merges STM + LTM entries, sorts by timestamp DESC
5. **Lazy Loading**: IntersectionObserver triggers `fetchLTM(nextCursor)` when user scrolls to bottom

## Backend Implementation

### New Endpoints

#### `/api/dashboard/stm`

**Handler**: `_dashboard_stm()` in `src/api/app.py`

**Provider**: `STMDataProvider` class in `src/api/dashboard.py`

**Implementation Details**:

```python
async def get_stm(self, user_id=None) -> dict[str, Any]:
    """
    Get short-term memory summaries from LangGraph checkpoints.
    
    Returns:
        List of bullet point entries from current-day summaries.
    """
    # 1. Get user's agents
    agent_ids = await self._get_user_agent_ids(user_id)
    
    # 2. Query LangGraph checkpoints
    #    - Filter: current day (server timezone)
    #    - Filter: thread_id startsWith "default-" OR "session-"
    #    - Extract: checkpoint.channel_values.summary
    
    # 3. Parse summary bullet points
    #    - Split by "\n-" or "\n•"
    #    - Each bullet point = one entry
    
    # 4. Map agent names
    #    - Use agent_lookup for agent_name
    
    # 5. Return entries
    return {
        "entries": [...],
        "hasMore": False  # STM always shows all at once
    }
```

**SQL Query** (conceptual):

```sql
SELECT 
    thread_id,
    checkpoint_id,
    checkpoint->'channel_values'->>'summary' as summary,
    checkpoint->'channel_values'->>'messages' as messages  -- for timestamp extraction
FROM langgraph.checkpoints
WHERE 
    thread_id LIKE 'default-%' OR thread_id LIKE 'session-%'
    AND checkpoint->'channel_values'->>'summary' IS NOT NULL
    AND DATE(created_at) = CURRENT_DATE  -- server timezone
ORDER BY checkpoint_id DESC
```

**Note**: Need to handle JSON parsing carefully. LangGraph checkpoint structure:
```json
{
  "channel_values": {
    "messages": [...],
    "summary": "- Alice 於 2025-11-15T14:30:00 提議...\n- Bob 同意出席..."
  }
}
```

#### `/api/dashboard/ltm`

**Handler**: `_dashboard_ltm()` in `src/api/app.py`

**Provider**: `LTMDataProvider` class in `src/api/dashboard.py`

**Implementation Details**:

```python
async def get_ltm(
    self, 
    user_id=None, 
    cursor: Optional[str] = None,  # ISO timestamp
    limit: int = 20
) -> dict[str, Any]:
    """
    Get long-term memory entries from Qdrant vector database.
    
    Args:
        cursor: Timestamp cursor for pagination (older than cursor)
        limit: Number of entries per page
        
    Returns:
        Paginated list of memory entries with nextCursor.
    """
    # 1. Get user's agents
    agent_ids = await self._get_user_agent_ids(user_id)
    
    # 2. Initialize QdrantVectorStore (need to pass agent_ids filter)
    #    - Current QdrantVectorStore is agent-scoped, need to modify
    #    OR: Query each agent separately and merge
    
    # 3. Query with pagination
    #    - Filter: agent_id in agent_ids
    #    - OrderBy: timestamp DESC
    #    - Limit: limit
    #    - Cursor: timestamp < cursor (if cursor provided)
    
    # 4. Map agent names
    #    - Use agent_lookup
    
    # 5. Determine hasMore
    #    - Query one more entry to check
    
    # 6. Return entries + nextCursor
    return {
        "entries": [...],
        "hasMore": bool,
        "nextCursor": "ISO timestamp" or None
    }
```

**Qdrant Query** (conceptual):

```python
# Need to modify QdrantVectorStore.get_all_entries() to support:
# - Multi-agent filtering (agent_id in [list])
# - Pagination (limit + offset OR cursor-based)
# - OrderBy timestamp DESC

results = self.client.scroll(
    collection_name=self.collection_name,
    scroll_filter=Filter(
        must=[
            FieldCondition(
                key="agent_id",
                match=MatchAny(value=agent_ids)  # New: multi-agent filter
            )
        ]
    ),
    limit=limit + 1,  # Check hasMore
    with_payload=True,
    with_vectors=False,
    # Need: OrderBy timestamp DESC (Qdrant supports this)
)
```

**Challenge**: Current `QdrantVectorStore` is agent-scoped (single agent_id). Need to:
- Option A: Modify to support multi-agent filtering
- Option B: Query each agent separately, merge results
- **Recommendation**: Option A (modify QdrantVectorStore)

### New Provider Classes

#### STMDataProvider

```python
@dataclass(slots=True)
class STMDataProvider:
    """Provide short-term memory summaries from LangGraph checkpoints."""
    
    async def get_stm(self, user_id=None) -> dict[str, Any]:
        """Get current-day STM entries."""
        agent_ids = await self._get_user_agent_ids(user_id)
        
        # Query LangGraph pool directly (GraphStore.pool)
        entries = await self._query_checkpoints(agent_ids)
        
        return {"entries": entries, "hasMore": False}
    
    async def _query_checkpoints(self, agent_ids: list) -> list[dict]:
        """Query langgraph.checkpoints table."""
        # Implementation details...
        
    async def _parse_summary_bullet_points(self, summary: str) -> list[str]:
        """Split summary into bullet points."""
        # Split by "\n-" or "\n•"
        # Return list of bullet point strings
```

#### LTMDataProvider

```python
@dataclass(slots=True)
class LTMDataProvider:
    """Provide long-term memory entries from Qdrant."""
    
    async def get_ltm(
        self, 
        user_id=None, 
        cursor: Optional[str] = None,
        limit: int = 20
    ) -> dict[str, Any]:
        """Get paginated LTM entries."""
        agent_ids = await self._get_user_agent_ids(user_id)
        
        # Initialize MultiAgentMemorySystem or QdrantVectorStore
        # Query with pagination
        entries = await self._query_qdrant(agent_ids, cursor, limit)
        
        return {
            "entries": entries,
            "hasMore": ...,
            "nextCursor": ...
        }
```

### Modifications to Existing Classes

#### QdrantVectorStore Modifications

**File**: `src/ltm/database/vector_store.py`

**Changes**:

1. Add multi-agent filtering support:
```python
def get_entries_for_agents(
    self, 
    agent_ids: List[str],
    limit: int = 20,
    cursor: Optional[str] = None  # timestamp cursor
) -> List[MemoryEntry]:
    """
    Get memory entries for multiple agents with pagination.
    
    Args:
        agent_ids: List of agent IDs to filter
        limit: Number of entries to return
        cursor: Timestamp cursor (return entries older than cursor)
        
    Returns:
        List of MemoryEntry sorted by timestamp DESC.
    """
    # Use Qdrant's MatchAny for multi-agent filter
    # Use OrderBy for timestamp sorting
    # Use cursor-based pagination
```

2. Add timestamp ordering:
```python
# Qdrant supports OrderBy in scroll API
results, _ = self.client.scroll(
    collection_name=self.collection_name,
    scroll_filter=Filter(...),
    limit=limit,
    order_by=OrderBy(
        key="timestamp",
        direction=Direction.DESC
    ),
    with_payload=True,
    with_vectors=False
)
```

## Frontend Implementation

### API Client

**File**: `frontend/src/api/dashboard.ts`

**New Functions**:

```typescript
export function fetchSTM(): Promise<STMPayload> {
  return requestJson<STMPayload>("/api/dashboard/stm");
}

export function fetchLTM(cursor?: string): Promise<LTMPayload> {
  const url = cursor 
    ? `/api/dashboard/ltm?cursor=${encodeURIComponent(cursor)}`
    : "/api/dashboard/ltm";
  return requestJson<LTMPayload>(url);
}
```

### Type Definitions

**File**: `frontend/src/types/dashboard.ts`

**New Types**:

```typescript
export interface STMEntry {
  id: string;
  kind: "stm";
  agent: string;
  timestamp: string;
  summary: string;  // Single bullet point
  sessionId: string;
  sessionName: string;
  status: SystemStatus;
}

export interface LTMEntry {
  id: string;
  kind: "ltm";
  agent: string;
  timestamp: string;
  summary: string;  // lossless_restatement
  status: SystemStatus;
}

export interface STMPayload {
  entries: STMEntry[];
  hasMore: false;
  source: string;
}

export interface LTMPayload {
  entries: LTMEntry[];
  hasMore: boolean;
  nextCursor: string | null;
  source: string;
}
```

### MemoryPage Component

**File**: `frontend/src/pages/MemoryPage.tsx`

**Changes**:

1. Remove `useDashboardResource(fetchMemory)` - use custom hooks instead
2. Add custom hook for merged STM + LTM loading
3. Implement IntersectionObserver for lazy loading

**New Hook**:

```typescript
function useMemoryEntries() {
  const [stmEntries, setStmEntries] = useState<STMEntry[]>([]);
  const [ltmEntries, setLtmEntries] = useState<LTMEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  
  // Load STM + initial LTM on mount
  useEffect(() => {
    async function loadInitial() {
      setIsLoading(true);
      const stmPayload = await fetchSTM();
      const ltmPayload = await fetchLTM();
      
      setStmEntries(stmPayload.entries);
      setLtmEntries(ltmPayload.entries);
      setHasMore(ltmPayload.hasMore);
      setNextCursor(ltmPayload.nextCursor);
      setIsLoading(false);
    }
    loadInitial();
  }, []);
  
  // Lazy loading function
  async function loadMore() {
    if (!hasMore || isLoadingMore || !nextCursor) return;
    
    setIsLoadingMore(true);
    const ltmPayload = await fetchLTM(nextCursor);
    
    setLtmEntries(prev => [...prev, ...ltmPayload.entries]);
    setHasMore(ltmPayload.hasMore);
    setNextCursor(ltmPayload.nextCursor);
    setIsLoadingMore(false);
  }
  
  // Merge and sort entries
  const mergedEntries = [...stmEntries, ...ltmEntries]
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  
  return {
    entries: mergedEntries,
    isLoading,
    isLoadingMore,
    hasMore,
    loadMore
  };
}
```

**IntersectionObserver Setup**:

```typescript
// Add at bottom of Timeline section
const bottomRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  if (!bottomRef.current || !hasMore) return;
  
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) {
        loadMore();
      }
    },
    { threshold: 0.1 }
  );
  
  observer.observe(bottomRef.current);
  return () => observer.disconnect();
}, [hasMore, loadMore]);

// In JSX:
<section className="timeline">
  {mergedEntries.map(entry => (
    <article key={`${entry.kind}-${entry.id}`} className="card timeline-item">
      {/* Same UI as existing timeline */}
    </article>
  ))}
  
  {/* Lazy loading trigger */}
  {hasMore && <div ref={bottomRef} className="timeline-loader">Loading more...</div>}
</section>
```

**Timeline Entry UI**:

Keep existing Timeline UI style. Each entry shows:
- Header: agent name + timestamp
- Summary: bullet point (STM) or lossless_restatement (LTM)
- Kind indicator: "STM" or "LTM" (optional badge)

## API Contract

### `/api/dashboard/stm`

**Request**:
```
GET /api/dashboard/stm
Headers: X-API-Key: <key>
```

**Response**:
```json
{
  "entries": [
    {
      "id": "checkpoint-123-bullet-1",
      "kind": "stm",
      "agent": "Otter",
      "timestamp": "2026-04-03T14:30:00Z",
      "summary": "Alice 於 2025-11-15T14:30:00 提議與 Bob 在 Starbucks 會面討論新產品。",
      "sessionId": "session-abc-123",
      "sessionName": "session-abc-123",
      "status": "healthy"
    }
  ],
  "hasMore": false,
  "source": "langgraph"
}
```

### `/api/dashboard/ltm`

**Request** (first page):
```
GET /api/dashboard/ltm
Headers: X-API-Key: <key>
```

**Request** (subsequent pages):
```
GET /api/dashboard/ltm?cursor=2026-04-02T10:00:00Z
Headers: X-API-Key: <key>
```

**Response**:
```json
{
  "entries": [
    {
      "id": "qdrant-point-uuid-1",
      "kind": "ltm",
      "agent": "Pandas",
      "timestamp": "2026-04-03T15:00:00Z",
      "summary": "部署事故跟進已補寫長期記憶。",
      "status": "healthy"
    }
  ],
  "hasMore": true,
  "nextCursor": "2026-04-02T10:00:00Z",
  "source": "qdrant"
}
```

## Error Handling

### Backend

1. **STM Query Fail**: Return empty entries with `source: "error"`
   ```json
   {"entries": [], "hasMore": false, "source": "error"}
   ```

2. **LTM Query Fail**: Same pattern, log error

3. **No Agents Found**: Return empty entries (valid case)

### Frontend

1. **API Error**: Show empty state with error message
2. **Network Error**: Show "網絡錯誤，請稍後重試"
3. **Loading Timeout**: After 10s, show "載入超時"

## Testing Strategy

### Backend Tests

**File**: `tests/unit/test_api_app.py`

**Test Cases**:

1. `test_stm_endpoint_returns_current_day_summaries()`
   - Mock LangGraph checkpoints
   - Verify bullet point parsing
   - Verify thread_id filtering

2. `test_ltm_endpoint_returns_paginated_entries()`
   - Mock QdrantVectorStore
   - Verify pagination logic
   - Verify multi-agent filtering

3. `test_stm_endpoint_filters_thread_id_prefix()`
   - Test "default-*" and "session-*" filtering
   - Verify exclusion of "ghost-*" threads

4. `test_ltm_endpoint_cursor_pagination()`
   - Test first page (no cursor)
   - Test subsequent pages (with cursor)
   - Verify nextCursor generation

### Frontend Tests

**File**: `frontend/src/pages/__tests__/MemoryPage.test.tsx`

**Test Cases**:

1. `test_merges_stm_and_ltm_entries()`
   - Mock both API calls
   - Verify sorted timeline

2. `test_lazy_loads_ltm_on_scroll()`
   - Mock IntersectionObserver
   - Verify loadMore call

3. `test_shows_empty_state_when_no_entries()`
   - Mock empty responses
   - Verify empty state UI

### Integration Tests

1. **Manual Test**: Run `review_stm()` to generate STM, verify shows in UI
2. **Manual Test**: Run `review_ltm()` to generate LTM, verify shows in UI
3. **Manual Test**: Scroll to bottom, verify lazy loading

## Implementation Checklist

### Phase 1: Backend (Priority: High)

1. ✅ Design spec approved by user
2. [ ] Create `STMDataProvider` class in `src/api/dashboard.py`
3. [ ] Create `LTMDataProvider` class in `src/api/dashboard.py`
4. [ ] Add `/api/dashboard/stm` endpoint in `src/api/app.py`
5. [ ] Add `/api/dashboard/ltm` endpoint in `src/api/app.py`
6. [ ] Modify `QdrantVectorStore` to support multi-agent filtering + pagination
7. [ ] Write backend unit tests
8. [ ] Test API endpoints manually

### Phase 2: Frontend (Priority: High)

1. [ ] Add `fetchSTM()` + `fetchLTM()` in `frontend/src/api/dashboard.ts`
2. [ ] Add `STMEntry` + `LTMEntry` types in `frontend/src/types/dashboard.ts`
3. [ ] Create `useMemoryEntries()` hook in `frontend/src/pages/MemoryPage.tsx`
4. [ ] Implement IntersectionObserver lazy loading
5. [ ] Update Timeline UI to show merged entries
6. [ ] Write frontend unit tests
7. [ ] Test UI manually

### Phase 3: Testing & Polish (Priority: Medium)

1. [ ] Run full test suite
2. [ ] Manual integration testing
3. [ ] Handle edge cases (empty states, errors)
4. [ ] Add i18n translations for new strings
5. [ ] Update AGENTS.md documentation

## Open Questions

1. **STM Timestamp Extraction**: How to extract timestamp from each bullet point?
   - Option A: Parse bullet point text (contains timestamp like "2025-11-15T14:30:00")
   - Option B: Use checkpoint's created_at as proxy
   - **Recommendation**: Option B (use checkpoint created_at, simpler)

2. **Session Name**: Should we show agent name instead of session_id?
   - Current decision: Show session_id as session_name
   - **Alternative**: Map session_id to agent_name (but need extra DB query)
   - **Recommendation**: Show session_id first version, iterate later

3. **STM Entry ID**: How to generate unique ID for each bullet point?
   - Recommendation: `checkpoint_id + "-bullet-" + index`

4. **LTM Entry ID**: Use Qdrant point ID or entry_id from payload?
   - Recommendation: Use Qdrant point ID (UUID, guaranteed unique)

5. **Empty State**: What to show when both STM + LTM are empty?
   - Recommendation: Show "目前沒有記憶記錄" message (same as current empty state)

## Future Enhancements (Out of Scope)

- Search functionality for LTM (semantic search)
- Filter by agent
- Filter by date range
- Show full metadata (keywords, persons, entities)
- STM/LTM separate view (tabs)
- Delete LTM entry

---

**End of Design Spec**
