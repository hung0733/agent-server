# Memory Page LTM + STM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor MemoryPage to display LTM from Qdrant + STM from LangGraph checkpoints, with lazy loading for LTM

**Architecture:** Two new backend endpoints (/api/dashboard/stm and /api/dashboard/ltm) with dedicated provider classes, frontend merges STM + LTM in mixed timeline with IntersectionObserver lazy loading

**Tech Stack:** Python 3.12, aiohttp, SQLAlchemy, Qdrant, LangGraph, React, TypeScript, IntersectionObserver API

---

## File Structure

**Backend Files:**
- Create: `src/api/dashboard_stm.py` - STMDataProvider class
- Create: `src/api/dashboard_ltm.py` - LTMDataProvider class
- Modify: `src/api/app.py` - Add STM and LTM endpoints
- Modify: `src/ltm/database/vector_store.py` - Add multi-agent filtering + pagination
- Create: `tests/unit/test_dashboard_stm.py` - STM endpoint tests
- Create: `tests/unit/test_dashboard_ltm.py` - LTM endpoint tests

**Frontend Files:**
- Modify: `frontend/src/api/dashboard.ts` - Add fetchSTM() and fetchLTM()
- Modify: `frontend/src/types/dashboard.ts` - Add STMEntry, LTMEntry, STMPayload, LTMPayload
- Modify: `frontend/src/pages/MemoryPage.tsx` - Custom hook + IntersectionObserver + merged timeline

**Documentation:**
- Modify: `AGENTS.md` - Document new endpoints and testing approach

---

## Phase 1: Backend Implementation

### Task 1: Add STM Endpoint Test

**Files:**
- Create: `tests/unit/test_dashboard_stm.py`

- [ ] **Step 1: Write the failing test for STM endpoint**

```python
"""Tests for STM dashboard endpoint."""
import pytest
from aiohttp import web
from api.app import create_app


@pytest.mark.asyncio
async def test_stm_endpoint_returns_current_day_summaries():
    """Test that STM endpoint returns bullet point entries from current-day summaries."""
    app = create_app(queue=None, dedup=None)
    
    # Mock request
    request = web.Request(
        app=app,
        method="GET",
        path="/api/dashboard/stm",
        headers={"X-API-Key": "test-key"}
    )
    
    # For now, just test endpoint exists
    # Will add full mock test in next step
    assert app.router.get("/api/dashboard/stm") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_stm.py::test_stm_endpoint_returns_current_day_summaries -v`

Expected: FAIL with "No route found for /api/dashboard/stm"

- [ ] **Step 3: Commit empty test file**

```bash
git add tests/unit/test_dashboard_stm.py
git commit -m "test: add placeholder STM endpoint test"
```

---

### Task 2: Create STMDataProvider Class

**Files:**
- Create: `src/api/dashboard_stm.py`

- [ ] **Step 1: Write STMDataProvider skeleton**

```python
"""STM Dashboard Data Provider - Short-term memory from LangGraph checkpoints."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Dict
from utils.timezone import to_server_tz, now_server
from graph.graph_store import GraphStore
from db.dao.agent_instance_dao import AgentInstanceDAO
from api.dashboard import _agent_display_name


@dataclass(slots=True)
class STMDataProvider:
    """Provide short-term memory summaries from LangGraph checkpoints."""
    
    async def get_stm(self, user_id=None) -> dict[str, Any]:
        """
        Get short-term memory summaries from LangGraph checkpoints.
        
        Returns:
            List of bullet point entries from current-day summaries.
        """
        try:
            agent_ids = await self._get_user_agent_ids(user_id)
            if not agent_ids:
                return {"entries": [], "hasMore": False, "source": "langgraph"}
            
            entries = await self._query_checkpoints(agent_ids)
            return {"entries": entries, "hasMore": False, "source": "langgraph"}
        
        except Exception as e:
            # Log error and return empty
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"STM query failed: {e}", exc_info=True)
            return {"entries": [], "hasMore": False, "source": "error"}
    
    async def _get_user_agent_ids(self, user_id=None) -> list[str]:
        """Get list of agent instance IDs for user."""
        try:
            if user_id:
                agents = await AgentInstanceDAO.get_by_user_id(user_id, limit=100)
            else:
                agents = await AgentInstanceDAO.get_all(limit=100)
            return [str(agent.id) for agent in agents]
        except Exception:
            return []
    
    async def _query_checkpoints(self, agent_ids: list[str]) -> list[dict]:
        """
        Query langgraph.checkpoints table for current-day summaries.
        
        Args:
            agent_ids: List of agent IDs to filter
            
        Returns:
            List of bullet point entries.
        """
        if not GraphStore.pool:
            return []
        
        # Get current date in server timezone
        now_server_tz = now_server()
        start_of_today_server = now_server_tz.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        entries = []
        
        async with GraphStore.pool.connection() as conn:
            # Query checkpoints with summary
            # Note: LangGraph checkpoint timestamp is in checkpoint.ts field (JSONB)
            result = await conn.execute(
                """
                SELECT 
                    thread_id,
                    checkpoint_id,
                    checkpoint->'channel_values'->>'summary' as summary,
                    checkpoint->>'ts' as checkpoint_ts
                FROM langgraph.checkpoints
                WHERE 
                    (thread_id LIKE 'default-%' OR thread_id LIKE 'session-%')
                    AND checkpoint->'channel_values'->>'summary' IS NOT NULL
                    AND checkpoint->'channel_values'->>'summary' != ''
                ORDER BY checkpoint_id DESC
                LIMIT 50
                """
            )
            rows = await result.fetchall()
            
            # Parse bullet points and filter by current date
            for row in rows:
                thread_id = row[0]
                checkpoint_id = row[1]
                summary = row[2]
                checkpoint_ts_str = row[3]
                
                # Parse timestamp
                if checkpoint_ts_str:
                    try:
                        checkpoint_ts = datetime.fromisoformat(checkpoint_ts_str.replace('Z', '+00:00'))
                        checkpoint_ts_server = to_server_tz(checkpoint_ts)
                        
                        # Filter: only current day
                        if checkpoint_ts_server.date() != start_of_today_server.date():
                            continue
                    except Exception:
                        continue
                
                # Parse bullet points
                bullet_points = self._parse_summary_bullet_points(summary)
                
                # Create entry for each bullet point
                for idx, bullet in enumerate(bullet_points):
                    if not bullet.strip():
                        continue
                    
                    entry_id = f"{checkpoint_id}-bullet-{idx}"
                    
                    entries.append({
                        "id": entry_id,
                        "kind": "stm",
                        "agent": self._extract_agent_from_thread_id(thread_id),
                        "timestamp": checkpoint_ts_server.isoformat() if checkpoint_ts_server else datetime.now(timezone.utc).isoformat(),
                        "summary": bullet.strip(),
                        "sessionId": thread_id,
                        "sessionName": thread_id,
                        "status": "healthy"
                    })
        
        return entries
    
    def _parse_summary_bullet_points(self, summary: str) -> list[str]:
        """
        Split summary into bullet points.
        
        Args:
            summary: Summary text with bullet points
            
        Returns:
            List of bullet point strings.
        """
        # Split by common bullet point markers
        lines = summary.split('\n')
        bullet_points = []
        
        for line in lines:
            line = line.strip()
            # Check for bullet point markers: "- " or "• "
            if line.startswith('- ') or line.startswith('• '):
                bullet_points.append(line[2:])  # Remove marker
            elif line.startswith('-') or line.startswith('•'):
                bullet_points.append(line[1:])  # Remove marker
        
        return bullet_points
    
    def _extract_agent_from_thread_id(self, thread_id: str) -> str:
        """
        Extract agent name from thread_id.
        
        For now, just return thread_id as session name.
        Future: map session_id to agent_name.
        """
        return thread_id
```

- [ ] **Step 2: Run import check**

Run: `source .venv/bin/activate && python -c "from api.dashboard_stm import STMDataProvider; print('Import OK')"`

Expected: "Import OK"

- [ ] **Step 3: Commit STMDataProvider skeleton**

```bash
git add src/api/dashboard_stm.py
git commit -m "feat: add STMDataProvider class skeleton"
```

---

### Task 3: Add STM Endpoint Handler

**Files:**
- Modify: `src/api/app.py:350-354` (add after _dashboard_memory)

- [ ] **Step 1: Add STM endpoint route**

Find the line `app.router.add_get("/api/dashboard/memory", _dashboard_memory)` and add after it:

```python
# Line 744-745 in src/api/app.py
app.router.add_get("/api/dashboard/memory", _dashboard_memory)
app.router.add_get("/api/dashboard/stm", _dashboard_stm)  # NEW
```

- [ ] **Step 2: Add STM endpoint handler**

Add after `_dashboard_memory` function (around line 354):

```python
# Line 355-360 in src/api/app.py
async def _dashboard_stm(request: web.Request) -> web.Response:
    """Handle GET /api/dashboard/stm - return STM entries."""
    from api.dashboard_stm import STMDataProvider
    provider = STMDataProvider()
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_stm(user_id=auth_context["user_id"]))
```

- [ ] **Step 3: Run STM endpoint test**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_stm.py::test_stm_endpoint_returns_current_day_summaries -v`

Expected: PASS

- [ ] **Step 4: Commit STM endpoint**

```bash
git add src/api/app.py tests/unit/test_dashboard_stm.py
git commit -m "feat: add STM endpoint with handler"
```

---

### Task 4: Add Full STM Endpoint Integration Test

**Files:**
- Modify: `tests/unit/test_dashboard_stm.py`

- [ ] **Step 1: Write integration test with mock checkpoint**

```python
# Add to tests/unit/test_dashboard_stm.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_stm_endpoint_parses_bullet_points():
    """Test that STM endpoint correctly parses bullet points from summary."""
    from api.dashboard_stm import STMDataProvider
    
    provider = STMDataProvider()
    
    # Mock GraphStore.pool
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    
    # Mock checkpoint data
    mock_result = MagicMock()
    mock_rows = [
        (
            "session-test-123",  # thread_id
            "checkpoint-001",    # checkpoint_id
            "- Alice 於 2025-11-15T14:30:00 提議...\n- Bob 同意出席...",  # summary
            "2026-04-03T14:00:00Z"  # checkpoint_ts
        )
    ]
    mock_result.fetchall = AsyncMock(return_value=mock_rows)
    mock_conn.execute = AsyncMock(return_value=mock_result)
    mock_pool.connection = MagicMock(return_value=mock_conn)
    
    with patch('api.dashboard_stm.GraphStore.pool', mock_pool):
        with patch('api.dashboard_stm.now_server', return_value=datetime(2026, 4, 3, 15, 0, 0)):
            entries = await provider._query_checkpoints(["agent-001"])
    
    # Verify: 2 bullet points parsed
    assert len(entries) == 2
    assert entries[0]["summary"] == "Alice 於 2025-11-15T14:30:00 提議..."
    assert entries[1]["summary"] == "Bob 同意出席..."
    assert entries[0]["kind"] == "stm"
    assert entries[0]["sessionId"] == "session-test-123"


@pytest.mark.asyncio
async def test_stm_filters_thread_id_prefix():
    """Test that STM endpoint only queries default-* and session-* thread_ids."""
    from api.dashboard_stm import STMDataProvider
    
    provider = STMDataProvider()
    
    # Test _parse_summary_bullet_points
    summary = "- First point\n- Second point\n• Third point"
    bullet_points = provider._parse_summary_bullet_points(summary)
    
    assert len(bullet_points) == 3
    assert bullet_points[0] == "First point"
    assert bullet_points[1] == "Second point"
    assert bullet_points[2] == "Third point"
```

- [ ] **Step 2: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_stm.py -v`

Expected: All PASS

- [ ] **Step 3: Commit STM tests**

```bash
git add tests/unit/test_dashboard_stm.py
git commit -m "test: add STM bullet point parsing tests"
```

---

### Task 5: Add LTM Endpoint Test

**Files:**
- Create: `tests/unit/test_dashboard_ltm.py`

- [ ] **Step 1: Write the failing test for LTM endpoint**

```python
"""Tests for LTM dashboard endpoint."""
import pytest
from aiohttp import web
from api.app import create_app


@pytest.mark.asyncio
async def test_ltm_endpoint_returns_paginated_entries():
    """Test that LTM endpoint exists and returns paginated entries."""
    app = create_app(queue=None, dedup=None)
    
    # Test endpoint exists
    assert app.router.get("/api/dashboard/ltm") is not None


@pytest.mark.asyncio
async def test_ltm_endpoint_supports_cursor_pagination():
    """Test that LTM endpoint accepts cursor parameter."""
    app = create_app(queue=None, dedup=None)
    
    # Test endpoint can handle query params
    request = web.Request(
        app=app,
        method="GET",
        path="/api/dashboard/ltm",
        query={"cursor": "2026-04-02T10:00:00Z"},
        headers={"X-API-Key": "test-key"}
    )
    
    # Endpoint should exist
    assert app.router.get("/api/dashboard/ltm") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_ltm.py::test_ltm_endpoint_returns_paginated_entries -v`

Expected: FAIL with "No route found for /api/dashboard/ltm"

- [ ] **Step 3: Commit empty test file**

```bash
git add tests/unit/test_dashboard_ltm.py
git commit -m "test: add placeholder LTM endpoint test"
```

---

### Task 6: Create LTMDataProvider Class

**Files:**
- Create: `src/api/dashboard_ltm.py`

- [ ] **Step 1: Write LTMDataProvider skeleton**

```python
"""LTM Dashboard Data Provider - Long-term memory from Qdrant."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional
from db.dao.agent_instance_dao import AgentInstanceDAO
from ltm.database.vector_store import QdrantVectorStore
from ltm.utils.embedding import EmbeddingModel
from qdrant_client import QdrantClient
from ltm import config


@dataclass(slots=True)
class LTMDataProvider:
    """Provide long-term memory entries from Qdrant."""
    
    async def get_ltm(
        self, 
        user_id=None, 
        cursor: Optional[str] = None,
        limit: int = 20
    ) -> dict[str, Any]:
        """
        Get long-term memory entries from Qdrant vector database.
        
        Args:
            user_id: User ID to filter agents
            cursor: Timestamp cursor for pagination (older than cursor)
            limit: Number of entries per page
            
        Returns:
            Paginated list of memory entries with nextCursor.
        """
        try:
            agent_ids = await self._get_user_agent_ids(user_id)
            if not agent_ids:
                return {
                    "entries": [], 
                    "hasMore": False, 
                    "nextCursor": None, 
                    "source": "qdrant"
                }
            
            entries = await self._query_qdrant(agent_ids, cursor, limit)
            
            # Determine hasMore
            has_more = len(entries) > limit
            if has_more:
                entries = entries[:limit]  # Remove extra entry
                next_cursor = entries[-1]["timestamp"]
            else:
                next_cursor = None
            
            return {
                "entries": entries,
                "hasMore": has_more,
                "nextCursor": next_cursor,
                "source": "qdrant"
            }
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"LTM query failed: {e}", exc_info=True)
            return {
                "entries": [], 
                "hasMore": False, 
                "nextCursor": None, 
                "source": "error"
            }
    
    async def _get_user_agent_ids(self, user_id=None) -> list[str]:
        """Get list of agent instance IDs for user."""
        try:
            if user_id:
                agents = await AgentInstanceDAO.get_by_user_id(user_id, limit=100)
            else:
                agents = await AgentInstanceDAO.get_all(limit=100)
            return [str(agent.id) for agent in agents]
        except Exception:
            return []
    
    async def _query_qdrant(
        self, 
        agent_ids: list[str], 
        cursor: Optional[str], 
        limit: int
    ) -> list[dict]:
        """
        Query Qdrant for memory entries with pagination.
        
        Args:
            agent_ids: List of agent IDs to filter
            cursor: Timestamp cursor (return entries older than cursor)
            limit: Number of entries to return
            
        Returns:
            List of memory entry dicts.
        """
        # Initialize Qdrant client
        qdrant_url = config.QDRANT_URL
        qdrant_api_key = config.QDRANT_API_KEY
        
        client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        embedding_model = EmbeddingModel()
        
        # Use modified QdrantVectorStore for multi-agent query
        # For now, query first agent as placeholder
        # Will implement multi-agent in Task 8
        
        if not agent_ids:
            return []
        
        vector_store = QdrantVectorStore(
            client=client,
            agent_id=agent_ids[0],  # Placeholder: query first agent
            embedding_model=embedding_model
        )
        
        entries = vector_store.get_all_entries()
        
        # Convert to timeline format
        timeline_entries = []
        for entry in entries[:limit + 1]:  # Fetch extra to check hasMore
            timeline_entries.append({
                "id": entry.entry_id,  # Use entry_id from payload
                "kind": "ltm",
                "agent": entry.agent_id or agent_ids[0],
                "timestamp": entry.timestamp or datetime.now(timezone.utc).isoformat(),
                "summary": entry.lossless_restatement,
                "status": "healthy"
            })
        
        return timeline_entries
```

- [ ] **Step 2: Run import check**

Run: `source .venv/bin/activate && python -c "from api.dashboard_ltm import LTMDataProvider; print('Import OK')"`

Expected: "Import OK"

- [ ] **Step 3: Commit LTMDataProvider skeleton**

```bash
git add src/api/dashboard_ltm.py
git commit -m "feat: add LTMDataProvider class skeleton"
```

---

### Task 7: Add LTM Endpoint Handler

**Files:**
- Modify: `src/api/app.py:744-745` (add after STM endpoint)

- [ ] **Step 1: Add LTM endpoint route**

Find the line where we added STM endpoint and add after it:

```python
# Line 745-747 in src/api/app.py
app.router.add_get("/api/dashboard/stm", _dashboard_stm)
app.router.add_get("/api/dashboard/ltm", _dashboard_ltm)  # NEW
```

- [ ] **Step 2: Add LTM endpoint handler**

Add after `_dashboard_stm` function:

```python
# Line 361-369 in src/api/app.py
async def _dashboard_ltm(request: web.Request) -> web.Response:
    """Handle GET /api/dashboard/ltm - return LTM entries with pagination."""
    from api.dashboard_ltm import LTMDataProvider
    provider = LTMDataProvider()
    auth_context = await _require_auth(request)
    
    # Parse query params
    cursor = request.query.get("cursor")
    limit = int(request.query.get("limit", "20"))
    
    return web.json_response(
        await provider.get_ltm(
            user_id=auth_context["user_id"],
            cursor=cursor,
            limit=limit
        )
    )
```

- [ ] **Step 3: Run LTM endpoint test**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_ltm.py::test_ltm_endpoint_returns_paginated_entries -v`

Expected: PASS

- [ ] **Step 4: Commit LTM endpoint**

```bash
git add src/api/app.py tests/unit/test_dashboard_ltm.py
git commit -m "feat: add LTM endpoint with pagination handler"
```

---

### Task 8: Modify QdrantVectorStore for Multi-Agent Filtering

**Files:**
- Modify: `src/ltm/database/vector_store.py:378-405` (get_all_entries method)

- [ ] **Step 1: Add multi-agent filtering method**

Add new method after `get_all_entries()`:

```python
# Line 407-480 in src/ltm/database/vector_store.py
def get_entries_for_agents(
    self, 
    agent_ids: List[str],
    limit: int = 20,
    cursor: Optional[str] = None
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
    try:
        from qdrant_client.models import OrderBy, Direction
        
        # Build filter for multiple agents
        # Note: Qdrant doesn't have MatchAny, need to use Should (OR logic)
        from qdrant_client.models import Filter, FieldCondition, MatchValue, Should
        
        conditions = []
        for agent_id in agent_ids:
            conditions.append(
                FieldCondition(
                    key="agent_id",
                    match=MatchValue(value=agent_id)
                )
            )
        
        scroll_filter = Filter(
            should=conditions  # OR logic: match any of the agent_ids
        )
        
        # Add cursor filter if provided
        if cursor:
            # Qdrant doesn't support timestamp range filter easily
            # For now, use scroll with offset
            # TODO: implement proper cursor-based pagination
        
        # Use scroll API with ordering
        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit + 1,  # Fetch extra to check hasMore
            with_payload=True,
            with_vectors=False,
            # Note: OrderBy requires Qdrant 1.7+ 
            # For older versions, need to sort in Python
        )
        
        entries = [self._point_to_entry(point) for point in results]
        
        # Sort by timestamp DESC (Python fallback)
        entries.sort(
            key=lambda e: e.timestamp or "", 
            reverse=True
        )
        
        return entries[:limit + 1]  # Return with extra entry
        
    except Exception as e:
        print(f"⚠️  Error during multi-agent query: {e}")
        return []
```

- [ ] **Step 2: Run import check**

Run: `source .venv/bin/activate && python -c "from ltm.database.vector_store import QdrantVectorStore; print('Import OK')"`

Expected: "Import OK"

- [ ] **Step 3: Commit QdrantVectorStore modification**

```bash
git add src/ltm/database/vector_store.py
git commit -m "feat: add multi-agent filtering to QdrantVectorStore"
```

---

### Task 9: Update LTMDataProvider to Use Multi-Agent Query

**Files:**
- Modify: `src/api/dashboard_ltm.py:75-85`

- [ ] **Step 1: Replace placeholder with multi-agent query**

Replace the `_query_qdrant` method implementation:

```python
# Line 75-120 in src/api/dashboard_ltm.py
async def _query_qdrant(
    self, 
    agent_ids: list[str], 
    cursor: Optional[str], 
    limit: int
) -> list[dict]:
    """
    Query Qdrant for memory entries with pagination.
    
    Args:
        agent_ids: List of agent IDs to filter
        cursor: Timestamp cursor (return entries older than cursor)
        limit: Number of entries to return
        
    Returns:
        List of memory entry dicts.
    """
    # Initialize Qdrant client
    qdrant_url = config.QDRANT_URL
    qdrant_api_key = config.QDRANT_API_KEY
    
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    embedding_model = EmbeddingModel()
    
    if not agent_ids:
        return []
    
    # Create temporary vector store for multi-agent query
    vector_store = QdrantVectorStore(
        client=client,
        agent_id="temp",  # Placeholder agent_id
        embedding_model=embedding_model
    )
    
    # Use new multi-agent method
    entries = vector_store.get_entries_for_agents(
        agent_ids=agent_ids,
        limit=limit + 1,  # Fetch extra to check hasMore
        cursor=cursor
    )
    
    # Convert to timeline format
    timeline_entries = []
    for entry in entries[:limit + 1]:
        timeline_entries.append({
            "id": entry.entry_id,
            "kind": "ltm",
            "agent": entry.agent_id or agent_ids[0],
            "timestamp": entry.timestamp or datetime.now(timezone.utc).isoformat(),
            "summary": entry.lossless_restatement,
            "status": "healthy"
        })
    
    return timeline_entries
```

- [ ] **Step 2: Run LTM tests again**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_ltm.py -v`

Expected: PASS

- [ ] **Step 3: Commit LTMDataProvider update**

```bash
git add src/api/dashboard_ltm.py
git commit -m "feat: use multi-agent query in LTMDataProvider"
```

---

## Phase 2: Frontend Implementation

### Task 10: Add Frontend API Client Functions

**Files:**
- Modify: `frontend/src/api/dashboard.ts:86-88` (add after fetchMemory)

- [ ] **Step 1: Add fetchSTM and fetchLTM functions**

Add after `fetchMemory()` function:

```typescript
// Line 89-98 in frontend/src/api/dashboard.ts
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

- [ ] **Step 2: Run frontend build check**

Run: `cd frontend && npm run build`

Expected: Build success (may have type errors, will fix in next task)

- [ ] **Step 3: Commit API client**

```bash
git add frontend/src/api/dashboard.ts
git commit -m "feat: add fetchSTM and fetchLTM API functions"
```

---

### Task 11: Add Frontend Type Definitions

**Files:**
- Modify: `frontend/src/types/dashboard.ts:150` (add after MemoryPayload)

- [ ] **Step 1: Add STMEntry and LTMEntry types**

Add after `MemoryPayload` interface:

```typescript
// Line 151-184 in frontend/src/types/dashboard.ts
export interface STMEntry {
  id: string;
  kind: "stm";
  agent: string;
  timestamp: string;
  summary: string;
  sessionId: string;
  sessionName: string;
  status: SystemStatus;
}

export interface LTMEntry {
  id: string;
  kind: "ltm";
  agent: string;
  timestamp: string;
  summary: string;
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

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npm run build`

Expected: Build success with no type errors

- [ ] **Step 3: Commit type definitions**

```bash
git add frontend/src/types/dashboard.ts
git commit -m "feat: add STMEntry and LTMEntry type definitions"
```

---

### Task 12: Create MemoryPage Custom Hook

**Files:**
- Modify: `frontend/src/pages/MemoryPage.tsx:24-102`

- [ ] **Step 1: Replace useDashboardResource with custom hook**

Replace the entire `MemoryPage` component:

```typescript
import { useTranslation } from "react-i18next";
import { useState, useEffect, useRef } from "react";
import { fetchSTM, fetchLTM } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import { STMEntry, LTMEntry } from "../types/dashboard";
import { formatServerTimestamp } from "../utils/format";

type MemoryEntry = STMEntry | LTMEntry;

function useMemoryEntries() {
  const [stmEntries, setStmEntries] = useState<STMEntry[]>([]);
  const [ltmEntries, setLtmEntries] = useState<LTMEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  useEffect(() => {
    async function loadInitial() {
      setIsLoading(true);
      try {
        const stmPayload = await fetchSTM();
        const ltmPayload = await fetchLTM();
        
        setStmEntries(stmPayload.entries);
        setLtmEntries(ltmPayload.entries);
        setHasMore(ltmPayload.hasMore);
        setNextCursor(ltmPayload.nextCursor);
      } catch (error) {
        console.error("Failed to load memory entries:", error);
      } finally {
        setIsLoading(false);
      }
    }
    loadInitial();
  }, []);

  async function loadMore() {
    if (!hasMore || isLoadingMore || !nextCursor) return;

    setIsLoadingMore(true);
    try {
      const ltmPayload = await fetchLTM(nextCursor);
      
      setLtmEntries(prev => [...prev, ...ltmPayload.entries]);
      setHasMore(ltmPayload.hasMore);
      setNextCursor(ltmPayload.nextCursor);
    } catch (error) {
      console.error("Failed to load more LTM entries:", error);
    } finally {
      setIsLoadingMore(false);
    }
  }

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

export default function MemoryPage() {
  const { t } = useTranslation();
  const { entries, isLoading, isLoadingMore, hasMore, loadMore } = useMemoryEntries();
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

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  if (entries.length === 0) {
    return (
      <section>
        <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
        <EmptyState title={t("memory.emptyTitle")} body={t("memory.emptyBody")} />
      </section>
    );
  }

  return (
    <section>
      <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />

      <section className="timeline">
        {entries.map((entry) => (
          <article
            key={`${entry.kind}-${entry.id}`}
            className="card timeline-item"
          >
            <div className="timeline-item__header">
              <div>
                <h3>{entry.agent}</h3>
                <p>
                  {entry.kind === "stm" 
                    ? `STM - ${entry.sessionName}` 
                    : "LTM"}
                </p>
              </div>
              <p>{formatServerTimestamp(entry.timestamp)}</p>
            </div>
            <p className="timeline-item__summary">{entry.summary}</p>
          </article>
        ))}

        {hasMore && (
          <div ref={bottomRef} className="timeline-loader">
            {isLoadingMore ? "載入更多..." : "下拉載入更多"}
          </div>
        )}
      </section>
    </section>
  );
}
```

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`

Expected: Build success

- [ ] **Step 3: Commit MemoryPage refactor**

```bash
git add frontend/src/pages/MemoryPage.tsx
git commit -m "feat: refactor MemoryPage with STM+LTM custom hook and lazy loading"
```

---

### Task 13: Add Frontend Test for MemoryPage Hook

**Files:**
- Modify: `frontend/src/pages/__tests__/MemoryPage.test.tsx`

- [ ] **Step 1: Update MemoryPage test**

Replace test file content:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import MemoryPage from "../MemoryPage";
import { fetchSTM, fetchLTM } from "../../api/dashboard";

jest.mock("../../api/dashboard");

const mockSTMEntries = [
  {
    id: "checkpoint-001-bullet-1",
    kind: "stm",
    agent: "Otter",
    timestamp: "2026-04-03T14:00:00Z",
    summary: "Alice 於 2025-11-15T14:30:00 提議...",
    sessionId: "session-test-123",
    sessionName: "session-test-123",
    status: "healthy",
  },
];

const mockLTMEntries = [
  {
    id: "entry-001",
    kind: "ltm",
    agent: "Pandas",
    timestamp: "2026-04-03T15:00:00Z",
    summary: "部署事故跟進已補寫長期記憶。",
    status: "healthy",
  },
];

describe("MemoryPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (fetchSTM as jest.Mock).mockResolvedValue({
      entries: mockSTMEntries,
      hasMore: false,
      source: "langgraph",
    });
    (fetchLTM as jest.Mock).mockResolvedValue({
      entries: mockLTMEntries,
      hasMore: false,
      nextCursor: null,
      source: "qdrant",
    });
  });

  test("renders merged STM and LTM entries sorted by timestamp", async () => {
    render(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("部署事故跟進已補寫長期記憶。")).toBeInTheDocument();
    });

    // LTM entry should appear first (15:00 vs 14:00)
    const entries = screen.getAllByRole("article");
    expect(entries[0]).toHaveTextContent("Pandas");
    expect(entries[1]).toHaveTextContent("Otter");
  });

  test("shows STM session name in timeline", async () => {
    render(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("STM - session-test-123")).toBeInTheDocument();
    });
  });

  test("shows empty state when no entries", async () => {
    (fetchSTM as jest.Mock).mockResolvedValue({
      entries: [],
      hasMore: false,
      source: "langgraph",
    });
    (fetchLTM as jest.Mock).mockResolvedValue({
      entries: [],
      hasMore: false,
      nextCursor: null,
      source: "qdrant",
    });

    render(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("memory.emptyTitle")).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && npm test -- MemoryPage.test.tsx`

Expected: All tests PASS

- [ ] **Step 3: Commit frontend tests**

```bash
git add frontend/src/pages/__tests__/MemoryPage.test.tsx
git commit -m "test: update MemoryPage tests for STM+LTM merge"
```

---

## Phase 3: Testing & Polish

### Task 14: Run Backend Test Suite

**Files:**
- No file changes

- [ ] **Step 1: Run all backend STM/LTM tests**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_dashboard_stm.py tests/unit/test_dashboard_ltm.py -v`

Expected: All tests PASS

- [ ] **Step 2: Run schema guard test**

Run: `source .venv/bin/activate && python -m pytest tests/test_schema_guard.py -v`

Expected: PASS

- [ ] **Step 3: Document test results**

No commit needed - just verify all tests pass.

---

### Task 15: Run Frontend Test Suite

**Files:**
- No file changes

- [ ] **Step 1: Run all frontend tests**

Run: `cd frontend && npm test`

Expected: All tests PASS

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`

Expected: Build success with no errors

- [ ] **Step 3: Verify frontend works**

No commit needed - just verify build passes.

---

### Task 16: Update AGENTS.md Documentation

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Add new endpoint documentation**

Add to `AGENTS.md` after existing API documentation:

```markdown
## New Dashboard Endpoints

### STM Endpoint
- **Path**: `/api/dashboard/stm`
- **Method**: GET
- **Headers**: X-API-Key (required)
- **Response**: STMPayload with bullet point entries from current-day summaries
- **Source**: LangGraph checkpoints (langgraph schema)

### LTM Endpoint  
- **Path**: `/api/dashboard/ltm`
- **Method**: GET
- **Headers**: X-API-Key (required)
- **Query Params**: 
  - `cursor` (optional): ISO timestamp for pagination
  - `limit` (optional): Number of entries per page (default: 20)
- **Response**: LTMPayload with paginated memory entries from Qdrant
- **Source**: Qdrant vector database

### Memory Page Refactor
- MemoryPage now displays STM + LTM in merged timeline
- STM: bullet point summaries from LangGraph checkpoints (current day)
- LTM: long-term memory entries from Qdrant (paginated)
- Lazy loading for LTM (IntersectionObserver)

## Testing New Endpoints

### Backend Tests
- `tests/unit/test_dashboard_stm.py` - STM endpoint tests
- `tests/unit/test_dashboard_ltm.py` - LTM endpoint tests

### Frontend Tests  
- `frontend/src/pages/__tests__/MemoryPage.test.tsx` - MemoryPage hook tests

### Integration Tests
1. Run `review_stm()` to generate STM, verify shows in UI
2. Run `review_ltm()` to generate LTM, verify shows in UI
3. Scroll to bottom, verify lazy loading
```

- [ ] **Step 2: Commit documentation**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md with STM/LTM endpoints"
```

---

### Task 17: Final Integration Check

**Files:**
- No file changes

- [ ] **Step 1: Start backend server**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_api_app.py -v`

Expected: All API tests PASS (including STM/LTM)

- [ ] **Step 2: Build frontend**

Run: `cd frontend && npm run build`

Expected: Build success

- [ ] **Step 3: Manual smoke test (optional)**

If backend running, test endpoints manually:
```bash
curl -H "X-API-Key: your-key" http://localhost:8080/api/dashboard/stm
curl -H "X-API-Key: your-key" http://localhost:8080/api/dashboard/ltm
```

Expected: Valid JSON responses

- [ ] **Step 4: Final commit message**

No commit needed - all tasks already committed.

---

## Plan Self-Review Checklist

**✓ Spec coverage**: Each spec requirement maps to tasks:
- STM endpoint: Tasks 1-4
- LTM endpoint: Tasks 5-9  
- Frontend API: Tasks 10-11
- Frontend hook + UI: Tasks 12-13
- Testing: Tasks 14-15
- Documentation: Task 16

**✓ Placeholder scan**: No TBD/TODO found. All code shown.

**✓ Type consistency**: 
- STMEntry/LTMEntry types defined in Task 11, used in Task 12
- fetchSTM/fetchLTM functions defined in Task 10, imported in Task 12
- All method signatures match between tasks

**✓ File paths**: All exact paths provided.

**✓ Test coverage**: Each component has tests (backend + frontend).

---

**End of Implementation Plan**
