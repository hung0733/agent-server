# pyright: reportMissingImports=false
"""Integration tests for PostgresSessionStorage — cross-session memory persistence layer.

Each test uses a Docker PostgreSQL container via the postgres_storage fixture.
Real integration tests for the storage layer.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from simplemem_cross_lite.types import (
    EventKind,
    ObservationType,
    RedactionLevel,
    SessionStatus,
)

if TYPE_CHECKING:
    from simplemem_cross_lite.storage.postgres import PostgresSessionStorage


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


async def _create_session(
    storage: "PostgresSessionStorage",
    content_id: str = "cs-1",
    project: str = "proj",
    tenant_id: str = "default",
    user_prompt: str | None = "do something",
) -> "SessionRecord":
    """Shortcut to create a session with sensible defaults."""
    return await storage.create_session(
        tenant_id=tenant_id,
        content_session_id=content_id,
        project=project,
        user_prompt=user_prompt,
    )


# ---------------------------------------------------------------------------
# TestPostgresSessionStorage
# ---------------------------------------------------------------------------


class TestPostgresSessionStorage:
    """Integration tests for PostgresSessionStorage using Docker PostgreSQL."""

    # -- Sessions ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_session(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Create a session and verify it is retrievable."""
        session = await _create_session(postgres_storage)

        assert session is not None
        assert session.content_session_id == "cs-1"
        assert session.project == "proj"
        assert session.status == SessionStatus.active
        assert session.memory_session_id  # non-empty UUID string
        assert session.id is not None and session.id > 0

        # Retrieve by content_session_id
        fetched = await postgres_storage.get_session_by_content_id("cs-1")
        assert fetched is not None
        assert fetched.memory_session_id == session.memory_session_id
        assert fetched.id == session.id

        # Retrieve by memory_session_id
        fetched2 = await postgres_storage.get_session_by_memory_id(session.memory_session_id)
        assert fetched2 is not None
        assert fetched2.content_session_id == "cs-1"

        # Retrieve by database id
        fetched3 = await postgres_storage.get_session_by_id(session.id)
        assert fetched3 is not None
        assert fetched3.memory_session_id == session.memory_session_id

    @pytest.mark.asyncio
    async def test_create_session_idempotent(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Creating the same content_session_id twice returns the same record."""
        s1 = await _create_session(postgres_storage, content_id="dup-1")
        s2 = await _create_session(postgres_storage, content_id="dup-1")

        # ON CONFLICT DO NOTHING means the second call is a no-op insert
        # both return the same row looked up by content_session_id.
        assert s1.memory_session_id == s2.memory_session_id
        assert s1.id == s2.id

    @pytest.mark.asyncio
    async def test_update_session_status(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Start active, update to completed, verify ended_at is set."""
        session = await _create_session(postgres_storage)
        assert session.status == SessionStatus.active

        await postgres_storage.update_session_status(
            session.memory_session_id, SessionStatus.completed
        )

        updated = await postgres_storage.get_session_by_memory_id(session.memory_session_id)
        assert updated is not None
        assert updated.status == SessionStatus.completed
        assert updated.ended_at is not None

    @pytest.mark.asyncio
    async def test_update_session_status_failed(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Update session to failed status and verify ended_at is set."""
        session = await _create_session(postgres_storage)
        
        await postgres_storage.update_session_status(
            session.memory_session_id, SessionStatus.failed
        )

        updated = await postgres_storage.get_session_by_memory_id(session.memory_session_id)
        assert updated is not None
        assert updated.status == SessionStatus.failed
        assert updated.ended_at is not None

    @pytest.mark.asyncio
    async def test_list_sessions(self, postgres_storage: "PostgresSessionStorage") -> None:
        """List sessions with various filters."""
        # Create sessions in different projects and tenants
        await _create_session(postgres_storage, content_id="list-1", project="alpha", tenant_id="tenant-a")
        await _create_session(postgres_storage, content_id="list-2", project="alpha", tenant_id="tenant-a")
        await _create_session(postgres_storage, content_id="list-3", project="beta", tenant_id="tenant-b")
        await _create_session(postgres_storage, content_id="list-4", project="alpha", tenant_id="tenant-a")

        # Complete one session
        s4 = await postgres_storage.get_session_by_content_id("list-4")
        assert s4 is not None
        await postgres_storage.update_session_status(s4.memory_session_id, SessionStatus.completed)

        # List all for tenant-a
        all_tenant_a = await postgres_storage.list_sessions(tenant_id="tenant-a")
        assert len(all_tenant_a) == 3

        # List by project
        alpha_sessions = await postgres_storage.list_sessions(project="alpha")
        assert len(alpha_sessions) == 3

        # List by status
        completed = await postgres_storage.list_sessions(status=SessionStatus.completed)
        assert len(completed) == 1
        assert completed[0].content_session_id == "list-4"

        # List with limit and offset
        limited = await postgres_storage.list_sessions(tenant_id="tenant-a", limit=2)
        assert len(limited) == 2

        offset = await postgres_storage.list_sessions(tenant_id="tenant-a", limit=2, offset=2)
        assert len(offset) == 1

    # -- Events ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_add_event(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Add events and verify they are retrievable in chronological order."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        eid1 = await postgres_storage.add_event(mid, EventKind.message, title="hello")
        await asyncio.sleep(0.02)
        eid2 = await postgres_storage.add_event(mid, EventKind.tool_use, title="run lint")
        await asyncio.sleep(0.02)
        eid3 = await postgres_storage.add_event(
            mid,
            EventKind.file_change,
            title="edit main.py",
            payload_json={"file": "main.py", "action": "edit"},
        )

        assert eid1 > 0
        assert eid2 > eid1
        assert eid3 > eid2

        events = await postgres_storage.get_events_for_session(mid)
        assert len(events) == 3
        assert events[0].title == "hello"
        assert events[0].kind == EventKind.message
        assert events[1].title == "run lint"
        assert events[1].kind == EventKind.tool_use
        assert events[2].title == "edit main.py"
        assert events[2].kind == EventKind.file_change

    @pytest.mark.asyncio
    async def test_get_events_for_session_filtered(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Test filtering events by kind."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        await postgres_storage.add_event(mid, EventKind.message, title="msg1")
        await postgres_storage.add_event(mid, EventKind.tool_use, title="tool1")
        await postgres_storage.add_event(mid, EventKind.message, title="msg2")
        await postgres_storage.add_event(mid, EventKind.note, title="note1")

        # Filter by message kind
        messages = await postgres_storage.get_events_for_session(mid, kinds=[EventKind.message])
        assert len(messages) == 2
        titles = {e.title for e in messages}
        assert titles == {"msg1", "msg2"}

        # Filter by multiple kinds
        selected = await postgres_storage.get_events_for_session(
            mid, kinds=[EventKind.tool_use, EventKind.note]
        )
        assert len(selected) == 2
        titles = {e.title for e in selected}
        assert titles == {"tool1", "note1"}

    @pytest.mark.asyncio
    async def test_get_events_session_isolation(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Add events to two sessions and verify isolation."""
        s1 = await _create_session(postgres_storage, content_id="iso-1")
        s2 = await _create_session(postgres_storage, content_id="iso-2")

        await postgres_storage.add_event(s1.memory_session_id, EventKind.note, title="s1-ev")
        await postgres_storage.add_event(s2.memory_session_id, EventKind.note, title="s2-ev-a")
        await postgres_storage.add_event(s2.memory_session_id, EventKind.system, title="s2-ev-b")

        ev1 = await postgres_storage.get_events_for_session(s1.memory_session_id)
        ev2 = await postgres_storage.get_events_for_session(s2.memory_session_id)

        assert len(ev1) == 1
        assert ev1[0].title == "s1-ev"

        assert len(ev2) == 2
        titles = {e.title for e in ev2}
        assert titles == {"s2-ev-a", "s2-ev-b"}

    @pytest.mark.asyncio
    async def test_event_redaction_level(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Test that redaction_level is properly stored and retrieved."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        await postgres_storage.add_event(
            mid, EventKind.message, title="redacted msg",
            redaction_level=RedactionLevel.partial
        )

        events = await postgres_storage.get_events_for_session(mid)
        assert len(events) == 1
        assert events[0].redaction_level == RedactionLevel.partial

    # -- Observations ------------------------------------------------------

    @pytest.mark.asyncio
    async def test_store_observation(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Store an observation and retrieve it."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        obs_id = await postgres_storage.store_observation(
            memory_session_id=mid,
            type=ObservationType.bugfix,
            title="Fixed null pointer",
            subtitle="in parser module",
            narrative="Discovered a null check was missing",
        )
        assert obs_id > 0

        observations = await postgres_storage.get_observations_for_session(mid)
        assert len(observations) == 1

        obs = observations[0]
        assert obs.obs_id == obs_id
        assert obs.title == "Fixed null pointer"
        assert obs.subtitle == "in parser module"
        assert obs.type == ObservationType.bugfix
        assert obs.narrative == "Discovered a null check was missing"
        assert obs.memory_session_id == mid

    @pytest.mark.asyncio
    async def test_store_observation_with_json(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Store observation with JSON fields."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        obs_id = await postgres_storage.store_observation(
            memory_session_id=mid,
            type=ObservationType.decision,
            title="Chose PostgreSQL",
            facts_json={"database": "PostgreSQL", "reason": "async support"},
            concepts_json=["async", "database"],
            files_json=["storage/postgres.py"],
        )
        assert obs_id > 0

        observations = await postgres_storage.get_observations_for_session(mid)
        assert len(observations) == 1
        assert observations[0].facts_json is not None
        assert observations[0].concepts_json is not None
        assert observations[0].files_json is not None

    @pytest.mark.asyncio
    async def test_get_observations_for_session(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify session-scoped observation retrieval."""
        s1 = await _create_session(postgres_storage, content_id="obs-s1")
        s2 = await _create_session(postgres_storage, content_id="obs-s2")

        await postgres_storage.store_observation(
            s1.memory_session_id, ObservationType.feature, "feat A"
        )
        await postgres_storage.store_observation(
            s2.memory_session_id, ObservationType.decision, "decision B"
        )
        await postgres_storage.store_observation(
            s2.memory_session_id, ObservationType.refactor, "refactor C"
        )

        obs_s1 = await postgres_storage.get_observations_for_session(s1.memory_session_id)
        obs_s2 = await postgres_storage.get_observations_for_session(s2.memory_session_id)

        assert len(obs_s1) == 1
        assert obs_s1[0].title == "feat A"

        assert len(obs_s2) == 2
        titles = {o.title for o in obs_s2}
        assert titles == {"decision B", "refactor C"}

    @pytest.mark.asyncio
    async def test_get_recent_observations(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Store observations across sessions and verify project filtering."""
        s1 = await _create_session(postgres_storage, content_id="ro-1", project="myproj")
        s2 = await _create_session(postgres_storage, content_id="ro-2", project="myproj")
        s3 = await _create_session(postgres_storage, content_id="ro-3", project="other")

        await postgres_storage.store_observation(s1.memory_session_id, ObservationType.bugfix, "fix 1")
        await asyncio.sleep(0.02)
        await postgres_storage.store_observation(
            s2.memory_session_id, ObservationType.feature, "feat 2"
        )
        await asyncio.sleep(0.02)
        await postgres_storage.store_observation(
            s3.memory_session_id, ObservationType.discovery, "disc 3"
        )

        # Only myproj observations
        recent = await postgres_storage.get_recent_observations("myproj", limit=10)
        assert len(recent) == 2
        titles = {o.title for o in recent}
        assert titles == {"fix 1", "feat 2"}

        # Filter by type
        bugfixes = await postgres_storage.get_recent_observations(
            "myproj", limit=10, types=[ObservationType.bugfix]
        )
        assert len(bugfixes) == 1
        assert bugfixes[0].title == "fix 1"

        # Other project
        other_obs = await postgres_storage.get_recent_observations("other", limit=10)
        assert len(other_obs) == 1
        assert other_obs[0].title == "disc 3"

    @pytest.mark.asyncio
    async def test_get_observations_by_ids(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Retrieve observations by IDs."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        obs_id1 = await postgres_storage.store_observation(
            mid, ObservationType.feature, "feat 1"
        )
        obs_id2 = await postgres_storage.store_observation(
            mid, ObservationType.bugfix, "fix 1"
        )
        obs_id3 = await postgres_storage.store_observation(
            mid, ObservationType.discovery, "disc 1"
        )

        # Get by IDs
        observations = await postgres_storage.get_observations_by_ids([obs_id1, obs_id3])
        assert len(observations) == 2
        titles = {o.title for o in observations}
        assert titles == {"feat 1", "disc 1"}

        # Empty list returns empty
        empty = await postgres_storage.get_observations_by_ids([])
        assert len(empty) == 0

    # -- Summaries ---------------------------------------------------------

    @pytest.mark.asyncio
    async def test_store_summary(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Store a summary and verify all fields round-trip."""
        session = await _create_session(postgres_storage)
        mid = session.memory_session_id

        sid = await postgres_storage.store_summary(
            memory_session_id=mid,
            request="build login page",
            investigated="auth flows",
            learned="OAuth2 best practices",
            completed="login form with validation",
            next_steps="add MFA support",
        )
        assert sid > 0

        summary = await postgres_storage.get_summary_for_session(mid)
        assert summary is not None
        assert summary.summary_id == sid
        assert summary.memory_session_id == mid
        assert summary.request == "build login page"
        assert summary.investigated == "auth flows"
        assert summary.learned == "OAuth2 best practices"
        assert summary.completed == "login form with validation"
        assert summary.next_steps == "add MFA support"
        assert summary.timestamp is not None

    @pytest.mark.asyncio
    async def test_get_summary_nonexistent(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Get summary for session without summary returns None."""
        session = await _create_session(postgres_storage)
        
        summary = await postgres_storage.get_summary_for_session(session.memory_session_id)
        assert summary is None

    @pytest.mark.asyncio
    async def test_get_recent_summaries(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Store 3 summaries, verify limit and DESC ordering."""
        # Create 3 sessions in "alpha" project with summaries
        for i in range(3):
            s = await _create_session(postgres_storage, content_id=f"sum-{i}", project="alpha")
            await asyncio.sleep(0.02)
            await postgres_storage.store_summary(
                memory_session_id=s.memory_session_id,
                request=f"task-{i}",
                completed=f"done-{i}",
            )
            await asyncio.sleep(0.02)

        # One session in a different project
        other = await _create_session(postgres_storage, content_id="sum-other", project="beta")
        await postgres_storage.store_summary(
            memory_session_id=other.memory_session_id,
            request="other-task",
        )

        # Limit to 2 — most recent first
        recent = await postgres_storage.get_recent_summaries("alpha", limit=2)
        assert len(recent) == 2
        assert recent[0].request == "task-2"
        assert recent[1].request == "task-1"

        # All alpha summaries
        all_alpha = await postgres_storage.get_recent_summaries("alpha", limit=10)
        assert len(all_alpha) == 3

        # Beta project
        beta = await postgres_storage.get_recent_summaries("beta", limit=10)
        assert len(beta) == 1
        assert beta[0].request == "other-task"

    # -- Context Manager ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_context_manager(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify the async context manager works correctly."""
        # The fixture already provides an initialized storage
        # Just verify we can use it
        session = await _create_session(postgres_storage)
        assert session is not None


# ---------------------------------------------------------------------------
# Tenant Isolation Tests
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Test tenant isolation for PostgreSQL storage."""

    @pytest.mark.asyncio
    async def test_session_tenant_isolation(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify sessions are isolated by tenant_id."""
        # Create sessions for different tenants
        tenant_a_session = await _create_session(
            postgres_storage, content_id="tenant-a-1", tenant_id="tenant-a", project="proj-a"
        )
        tenant_b_session = await _create_session(
            postgres_storage, content_id="tenant-b-1", tenant_id="tenant-b", project="proj-b"
        )

        # Verify they have different memory_session_ids
        assert tenant_a_session.memory_session_id != tenant_b_session.memory_session_id

        # List sessions by tenant
        tenant_a_sessions = await postgres_storage.list_sessions(tenant_id="tenant-a")
        tenant_b_sessions = await postgres_storage.list_sessions(tenant_id="tenant-b")

        assert len(tenant_a_sessions) == 1
        assert tenant_a_sessions[0].tenant_id == "tenant-a"

        assert len(tenant_b_sessions) == 1
        assert tenant_b_sessions[0].tenant_id == "tenant-b"

    @pytest.mark.asyncio
    async def test_events_cross_tenant_inaccessible(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify events from one tenant's session cannot be accessed via another tenant's session."""
        # Create sessions for different tenants
        session_a = await _create_session(
            postgres_storage, content_id="cross-tenant-a", tenant_id="tenant-a"
        )
        session_b = await _create_session(
            postgres_storage, content_id="cross-tenant-b", tenant_id="tenant-b"
        )

        # Add events to tenant A's session
        await postgres_storage.add_event(
            session_a.memory_session_id, EventKind.message, title="tenant-a-secret"
        )

        # Verify tenant B cannot see tenant A's events through session query
        events_a = await postgres_storage.get_events_for_session(session_a.memory_session_id)
        events_b = await postgres_storage.get_events_for_session(session_b.memory_session_id)

        assert len(events_a) == 1
        assert events_a[0].title == "tenant-a-secret"
        assert len(events_b) == 0

    @pytest.mark.asyncio
    async def test_observations_tenant_isolation(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify observations are isolated by project/tenant association."""
        # Create sessions for different tenants in different projects
        session_a = await _create_session(
            postgres_storage, content_id="obs-tenant-a", tenant_id="tenant-a", project="proj-a"
        )
        session_b = await _create_session(
            postgres_storage, content_id="obs-tenant-b", tenant_id="tenant-b", project="proj-b"
        )

        # Store observations
        await postgres_storage.store_observation(
            session_a.memory_session_id, ObservationType.feature, "tenant-a-feature"
        )
        await postgres_storage.store_observation(
            session_b.memory_session_id, ObservationType.bugfix, "tenant-b-bugfix"
        )

        # Verify project-based isolation
        obs_a = await postgres_storage.get_recent_observations("proj-a", limit=10)
        obs_b = await postgres_storage.get_recent_observations("proj-b", limit=10)

        assert len(obs_a) == 1
        assert obs_a[0].title == "tenant-a-feature"

        assert len(obs_b) == 1
        assert obs_b[0].title == "tenant-b-bugfix"

    @pytest.mark.asyncio
    async def test_summaries_tenant_isolation(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify summaries are isolated by project/tenant association."""
        # Create sessions for different tenants in different projects
        session_a = await _create_session(
            postgres_storage, content_id="sum-tenant-a", tenant_id="tenant-a", project="proj-alpha"
        )
        session_b = await _create_session(
            postgres_storage, content_id="sum-tenant-b", tenant_id="tenant-b", project="proj-beta"
        )

        # Store summaries
        await postgres_storage.store_summary(
            memory_session_id=session_a.memory_session_id,
            request="tenant-a request",
            completed="tenant-a work",
        )
        await postgres_storage.store_summary(
            memory_session_id=session_b.memory_session_id,
            request="tenant-b request",
            completed="tenant-b work",
        )

        # Verify project-based isolation
        sums_a = await postgres_storage.get_recent_summaries("proj-alpha", limit=10)
        sums_b = await postgres_storage.get_recent_summaries("proj-beta", limit=10)

        assert len(sums_a) == 1
        assert sums_a[0].request == "tenant-a request"

        assert len(sums_b) == 1
        assert sums_b[0].request == "tenant-b request"

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_tenant(self, postgres_storage: "PostgresSessionStorage") -> None:
        """Verify multiple sessions for same tenant are properly grouped."""
        tenant_id = "shared-tenant"

        # Create multiple sessions for the same tenant
        s1 = await _create_session(
            postgres_storage, content_id="multi-1", tenant_id=tenant_id, project="shared-proj"
        )
        s2 = await _create_session(
            postgres_storage, content_id="multi-2", tenant_id=tenant_id, project="shared-proj"
        )
        s3 = await _create_session(
            postgres_storage, content_id="multi-3", tenant_id=tenant_id, project="shared-proj"
        )

        # Add events to different sessions
        await postgres_storage.add_event(s1.memory_session_id, EventKind.message, title="event-1")
        await postgres_storage.add_event(s2.memory_session_id, EventKind.note, title="event-2")
        await postgres_storage.add_event(s3.memory_session_id, EventKind.system, title="event-3")

        # List all sessions for tenant
        sessions = await postgres_storage.list_sessions(tenant_id=tenant_id)
        assert len(sessions) == 3

        # Verify each session's events are isolated
        events_1 = await postgres_storage.get_events_for_session(s1.memory_session_id)
        events_2 = await postgres_storage.get_events_for_session(s2.memory_session_id)
        events_3 = await postgres_storage.get_events_for_session(s3.memory_session_id)

        assert len(events_1) == 1
        assert events_1[0].title == "event-1"

        assert len(events_2) == 1
        assert events_2[0].title == "event-2"

        assert len(events_3) == 1
        assert events_3[0].title == "event-3"


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test error conditions and edge cases."""

    @pytest.mark.asyncio
    async def test_get_session_nonexistent_content_id(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get session by nonexistent content_id returns None."""
        result = await postgres_storage.get_session_by_content_id("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_nonexistent_memory_id(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get session by nonexistent memory_session_id returns None."""
        result = await postgres_storage.get_session_by_memory_id("nonexistent-memory-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_nonexistent_id(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get session by nonexistent database ID returns None."""
        result = await postgres_storage.get_session_by_id(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_events_empty_session(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get events for session with no events returns empty list."""
        session = await _create_session(postgres_storage)
        events = await postgres_storage.get_events_for_session(session.memory_session_id)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_get_observations_empty_session(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get observations for session with no observations returns empty list."""
        session = await _create_session(postgres_storage)
        observations = await postgres_storage.get_observations_for_session(session.memory_session_id)
        assert len(observations) == 0

    @pytest.mark.asyncio
    async def test_get_recent_observations_empty_project(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get recent observations for nonexistent project returns empty list."""
        observations = await postgres_storage.get_recent_observations("nonexistent-project")
        assert len(observations) == 0

    @pytest.mark.asyncio
    async def test_get_recent_summaries_empty_project(
        self, postgres_storage: "PostgresSessionStorage"
    ) -> None:
        """Get recent summaries for nonexistent project returns empty list."""
        summaries = await postgres_storage.get_recent_summaries("nonexistent-project")
        assert len(summaries) == 0


# ---------------------------------------------------------------------------
# Import SessionRecord at end to avoid circular imports
# ---------------------------------------------------------------------------

from simplemem_cross_lite.types import SessionRecord