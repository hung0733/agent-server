# pyright: reportMissingImports=false, reportGeneralTypeIssues=false, reportAssignmentType=false
"""
Session Manager for simplemem-cross-lite.

Orchestrates the full lifecycle of a cross-session memory session using
PostgreSQL for session storage and Qdrant for vector storage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from simplemem_cross_lite.types import (
    CrossObservation,
    EventKind,
    FinalizationReport,
    ObservationType,
    RedactionLevel,
    SessionEvent,
    SessionRecord,
    SessionStatus,
    SessionSummary,
)
from simplemem_cross_lite.storage.base import SessionStorage, VectorStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal classes for event collection
# ---------------------------------------------------------------------------


class _CollectedEvent:
    """In-memory representation of a collected event before persistence."""

    __slots__ = ("kind", "title", "payload", "timestamp")

    def __init__(
        self,
        kind: EventKind,
        title: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.kind = kind
        self.title = title
        self.payload = payload
        self.timestamp = datetime.now(timezone.utc)


class EventCollector:
    """Collects session events in memory before flushing to storage.

    Acts as a write-behind buffer so that the hot path (recording events)
    stays fast while persistence can happen in a batch during finalization.
    """

    def __init__(self, memory_session_id: str) -> None:
        self.memory_session_id = memory_session_id
        self._events: List[_CollectedEvent] = []

    def add_event(
        self,
        kind: EventKind,
        title: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> _CollectedEvent:
        """Append an event to the in-memory buffer and return it."""
        event = _CollectedEvent(kind=kind, title=title, payload=payload)
        self._events.append(event)
        return event

    def flush(self) -> List[_CollectedEvent]:
        """Return all buffered events and clear the internal buffer."""
        events = list(self._events)
        self._events.clear()
        return events

    @property
    def event_count(self) -> int:
        return len(self._events)


class ObservationExtractor:
    """Extracts structured observations from a list of session events.

    This is a rule-based implementation. When the full collectors module
    is available it can be replaced by a richer (potentially LLM-assisted) extractor.
    """

    _KIND_TO_OBS_TYPE: Dict[str, ObservationType] = {
        "tool_use": ObservationType.change,
        "file_change": ObservationType.change,
        "message": ObservationType.discovery,
        "note": ObservationType.discovery,
        "system": ObservationType.discovery,
    }

    def extract_from_events(
        self,
        events: List[Any],
        memory_session_id: str,
    ) -> List[CrossObservation]:
        """Derive observations from a sequence of collected events.

        The extraction uses simple heuristics:
        * ``tool_use`` and ``file_change`` events become *change* observations.
        * ``message`` and ``note`` events become *discovery* observations.
        * Events with no title are skipped.
        """
        observations: List[CrossObservation] = []
        for event in events:
            title = getattr(event, "title", None)
            if not title:
                continue
            kind_value = (
                event.kind.value
                if hasattr(event.kind, "value")
                else str(event.kind)
            )
            obs_type = self._KIND_TO_OBS_TYPE.get(
                kind_value, ObservationType.discovery
            )
            payload = getattr(event, "payload", None)
            narrative: Optional[str] = None
            if isinstance(payload, dict):
                narrative = payload.get("content") or payload.get("output")
                if narrative and len(str(narrative)) > 500:
                    narrative = str(narrative)[:500] + "..."

            observations.append(
                CrossObservation(
                    memory_session_id=memory_session_id,
                    timestamp=getattr(
                        event, "timestamp", datetime.now(timezone.utc)
                    ),
                    type=obs_type,
                    title=title,
                    narrative=narrative,
                )
            )
        return observations


# ---------------------------------------------------------------------------
# Dialogue class (internal for memory processing)
# ---------------------------------------------------------------------------


class Dialogue:
    """Minimal Dialogue class for memory processing."""

    def __init__(
        self,
        dialogue_id: int,
        speaker: str,
        content: str,
        timestamp: Optional[str] = None,
    ) -> None:
        self.dialogue_id = dialogue_id
        self.speaker = speaker
        self.content = content
        self.timestamp = timestamp


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Orchestrates the full lifecycle of a cross-session memory session.

    Responsibilities
    ----------------
    * **Start** — create a ``SessionRecord`` in storage, initialise an
      ``EventCollector`` for the session.
    * **Record** — capture events (messages, tool-use, file changes, etc.)
      through the ``EventCollector`` with convenience helpers.
    * **Finalize** — flush buffered events to storage, extract observations,
      optionally run a memory pipeline to produce memory entries, store 
      everything with provenance in the vector store, and generate a summary.
    * **End** — mark the session completed/failed in storage.
    * **Query** — retrieve session records, events, and observations.

    Parameters
    ----------
    session_storage:
        The storage backend for sessions, events, observations, summaries.
        Must implement the SessionStorage interface (async methods).
    vector_store:
        The vector store for cross-session memory entries.
        Must implement the VectorStore interface (async methods).
    memory_processor:
        Optional reference to a memory processor instance (duck-typed).
        When provided, finalization will also run the memory pipeline
        to produce memory entries.
    """

    def __init__(
        self,
        session_storage: SessionStorage,
        vector_store: VectorStore,
        memory_processor: Optional[Any] = None,
    ) -> None:
        self._storage = session_storage
        self._vector_store = vector_store
        self._memory_processor = memory_processor
        self._collectors: Dict[str, EventCollector] = {}
        self._collectors_lock = threading.RLock()
        self._observation_extractor: ObservationExtractor = ObservationExtractor()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def start_session(
        self,
        tenant_id: str,
        content_session_id: str,
        project: str,
        user_prompt: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> SessionRecord:
        """Create a new session and prepare its event collector.

        Parameters
        ----------
        tenant_id:
            Tenant identifier for multi-tenant isolation.
        content_session_id:
            The external (host-side) session identifier.
        project:
            Project name this session belongs to.
        user_prompt:
            Optional initial user prompt / request that started the session.
        metadata:
            Optional metadata dictionary for the session.

        Returns
        -------
        SessionRecord
            The newly-created session persisted in storage.
        """
        session = await self._storage.create_session(
            tenant_id=tenant_id,
            content_session_id=content_session_id,
            project=project,
            user_prompt=user_prompt,
            metadata=metadata,
        )
        memory_session_id = session.memory_session_id
        with self._collectors_lock:
            self._collectors[memory_session_id] = EventCollector(memory_session_id)
        logger.info(
            "Started session %s (content_id=%s, project=%s)",
            memory_session_id,
            content_session_id,
            project,
        )
        return session

    async def record_event(
        self,
        memory_session_id: str,
        kind: EventKind,
        title: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record an event via the in-memory collector then persist to storage.

        Parameters
        ----------
        memory_session_id:
            Session to attach the event to.
        kind:
            The ``EventKind`` enum value.
        title:
            Short human-readable title for the event.
        payload:
            Arbitrary JSON-serialisable payload dict.

        Returns
        -------
        int
            The ``event_id`` assigned by storage.
        """
        collector = self._get_collector(memory_session_id)
        collector.add_event(kind=kind, title=title, payload=payload)
        event_id = await self._storage.add_event(
            memory_session_id=memory_session_id,
            kind=kind,
            title=title,
            payload_json=payload,
        )
        logger.debug(
            "Recorded event %d (%s) for session %s",
            event_id,
            kind.value if hasattr(kind, "value") else kind,
            memory_session_id,
        )
        return event_id

    async def record_message(
        self,
        memory_session_id: str,
        content: str,
        role: str = "user",
    ) -> int:
        """Convenience: record a chat message event.

        Parameters
        ----------
        memory_session_id:
            Target session.
        content:
            The message body.
        role:
            Speaker role (``"user"``, ``"assistant"``, ``"system"``).

        Returns
        -------
        int
            The ``event_id``.
        """
        return await self.record_event(
            memory_session_id=memory_session_id,
            kind=EventKind.message,
            title=f"{role} message",
            payload={"role": role, "content": content},
        )

    async def record_tool_use(
        self,
        memory_session_id: str,
        tool_name: str,
        tool_input: str,
        tool_output: str,
    ) -> int:
        """Convenience: record a tool invocation event.

        Parameters
        ----------
        memory_session_id:
            Target session.
        tool_name:
            Name of the tool that was called.
        tool_input:
            Serialised input passed to the tool.
        tool_output:
            Serialised output returned by the tool.

        Returns
        -------
        int
            The ``event_id``.
        """
        return await self.record_event(
            memory_session_id=memory_session_id,
            kind=EventKind.tool_use,
            title=f"tool:{tool_name}",
            payload={
                "tool": tool_name,
                "input": tool_input,
                "output": tool_output,
            },
        )

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_session(self, memory_session_id: str) -> FinalizationReport:
        """Finalize a session: persist events, extract observations, run
        the optional memory pipeline, generate a summary, and return a
        ``FinalizationReport``.

        Steps
        -----
        1. Flush the ``EventCollector`` buffer for this session.
        2. Persist any remaining buffered events to storage.
        3. Extract observations from events via ``ObservationExtractor``.
        4. Store observations in storage.
        5. If ``memory_processor`` is available, convert events to ``Dialogue``
           objects, run the memory pipeline, store the resulting memory entries 
           in ``vector_store`` with provenance.
        6. Generate a template-based summary and store via storage.
        7. Return the ``FinalizationReport``.

        Error handling is resilient — partial failures in one step do not
        prevent subsequent steps from executing.
        """
        session = await self._storage.get_session_by_memory_id(memory_session_id)
        if session is None:
            logger.error("Cannot finalize unknown session: %s", memory_session_id)
            return FinalizationReport(
                memory_session_id=memory_session_id,
                observations_count=0,
                summary_generated=False,
                entries_stored=0,
                consolidation_triggered=False,
            )

        # -- Step 1: Flush EventCollector buffer --------------------------
        flushed_events: List[Any] = []
        try:
            with self._collectors_lock:
                collector = self._collectors.get(memory_session_id)
            if collector is not None:
                flushed_events = collector.flush()
                logger.info(
                    "Flushed %d buffered events for session %s",
                    len(flushed_events),
                    memory_session_id,
                )
        except Exception:
            logger.exception(
                "Error flushing collector for session %s", memory_session_id
            )

        # -- Step 2: Persist any flushed events not yet in storage --------
        persisted_event_count = 0
        for ev in flushed_events:
            try:
                await self._storage.add_event(
                    memory_session_id=memory_session_id,
                    kind=ev.kind,
                    title=getattr(ev, "title", None),
                    payload_json=getattr(ev, "payload", None),
                )
                persisted_event_count += 1
            except Exception:
                logger.exception(
                    "Error persisting flushed event for session %s",
                    memory_session_id,
                )

        if persisted_event_count:
            logger.info(
                "Persisted %d flushed events for session %s",
                persisted_event_count,
                memory_session_id,
            )

        # -- Step 3: Extract observations from ALL events -----------------
        all_events = await self._storage.get_events_for_session(memory_session_id)
        observations: List[CrossObservation] = []
        try:
            observations = self._observation_extractor.extract_from_events(
                events=all_events,
                memory_session_id=memory_session_id,
            )
            logger.info(
                "Extracted %d observations for session %s",
                len(observations),
                memory_session_id,
            )
        except Exception:
            logger.exception(
                "Error extracting observations for session %s", memory_session_id
            )

        # -- Step 4: Store observations in storage -------------------------
        stored_obs_count = 0
        for obs in observations:
            try:
                obs_type = (
                    obs.type
                    if isinstance(obs.type, ObservationType)
                    else ObservationType(obs.type)
                )
                await self._storage.store_observation(
                    memory_session_id=memory_session_id,
                    type=obs_type,
                    title=obs.title,
                    subtitle=obs.subtitle,
                    narrative=obs.narrative,
                )
                stored_obs_count += 1
            except Exception:
                logger.exception(
                    "Error storing observation '%s' for session %s",
                    obs.title,
                    memory_session_id,
                )

        # -- Step 5: Memory pipeline (optional) ---------------------------
        entries_stored = 0
        if self._memory_processor is not None:
            try:
                entries_stored = await self._run_memory_pipeline(
                    memory_session_id=memory_session_id,
                    session=session,
                    events=all_events,
                )
            except Exception:
                logger.exception(
                    "Error running memory pipeline for session %s",
                    memory_session_id,
                )

        # -- Step 6: Generate and store summary ---------------------------
        summary_generated = False
        try:
            summary_generated = await self._generate_and_store_summary(
                memory_session_id=memory_session_id,
                session=session,
                event_count=len(all_events),
                observation_count=stored_obs_count,
                entries_stored=entries_stored,
            )
        except Exception:
            logger.exception(
                "Error generating summary for session %s", memory_session_id
            )

        # -- Clean up collector -------------------------------------------
        with self._collectors_lock:
            self._collectors.pop(memory_session_id, None)

        report = FinalizationReport(
            memory_session_id=memory_session_id,
            observations_count=stored_obs_count,
            summary_generated=summary_generated,
            entries_stored=entries_stored,
            consolidation_triggered=False,
        )
        logger.info(
            "Finalized session %s: observations=%d, entries=%d, summary=%s",
            memory_session_id,
            stored_obs_count,
            entries_stored,
            summary_generated,
        )
        return report

    # ------------------------------------------------------------------
    # Session end
    # ------------------------------------------------------------------

    async def end_session(
        self,
        memory_session_id: str,
        status: SessionStatus = SessionStatus.completed,
    ) -> None:
        """Mark a session as completed or failed in storage.

        Parameters
        ----------
        memory_session_id:
            Session to close.
        status:
            Final status — typically ``completed`` or ``failed``.
        """
        await self._storage.update_session_status(
            memory_session_id=memory_session_id,
            status=status,
        )
        # Clean up any lingering collector
        with self._collectors_lock:
            self._collectors.pop(memory_session_id, None)
        logger.info("Ended session %s with status=%s", memory_session_id, status.value)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_session(self, memory_session_id: str) -> Optional[SessionRecord]:
        """Retrieve a session record by its memory session id."""
        return await self._storage.get_session_by_memory_id(memory_session_id)

    async def get_events(self, memory_session_id: str) -> List[SessionEvent]:
        """Retrieve all persisted events for a session, ordered by time."""
        return await self._storage.get_events_for_session(memory_session_id)

    async def get_observations(self, memory_session_id: str) -> List[CrossObservation]:
        """Retrieve all observations for a session."""
        return await self._storage.get_observations_for_session(memory_session_id)

    async def get_summary(self, memory_session_id: str) -> Optional[SessionSummary]:
        """Retrieve summary for a session."""
        return await self._storage.get_summary_for_session(memory_session_id)

    async def list_sessions(
        self,
        tenant_id: Optional[str] = None,
        project: Optional[str] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SessionRecord]:
        """List sessions with optional filters."""
        return await self._storage.list_sessions(
            tenant_id=tenant_id,
            project=project,
            status=status,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_collector(self, memory_session_id: str) -> EventCollector:
        """Return the EventCollector for the session, creating one on demand."""
        with self._collectors_lock:
            collector = self._collectors.get(memory_session_id)
            if collector is None:
                collector = EventCollector(memory_session_id)
                self._collectors[memory_session_id] = collector
                logger.debug(
                    "Created on-demand EventCollector for session %s",
                    memory_session_id,
                )
        return collector

    async def _run_memory_pipeline(
        self,
        memory_session_id: str,
        session: SessionRecord,
        events: List[SessionEvent],
    ) -> int:
        """Convert events to Dialogues, run memory pipeline, store entries.

        Returns the number of memory entries stored in the vector store.
        """
        if self._memory_processor is None:
            return 0

        # Build Dialogue objects from message events
        dialogues: List[Dialogue] = []
        dialogue_id = 0
        for event in events:
            if event.kind != EventKind.message:
                continue
            payload = self._parse_payload(event.payload_json)
            role = payload.get("role", "user") if payload else "user"
            content = payload.get("content", "") if payload else ""
            if not content:
                content = event.title or ""
            if not content:
                continue
            dialogues.append(
                Dialogue(
                    dialogue_id=dialogue_id,
                    speaker=role,
                    content=content,
                    timestamp=(
                        event.timestamp.isoformat()
                        if isinstance(event.timestamp, datetime)
                        else str(event.timestamp)
                    ),
                )
            )
            dialogue_id += 1

        if not dialogues:
            logger.debug(
                "No message events to feed memory processor for session %s",
                memory_session_id,
            )
            return 0

        # Feed dialogues into memory processor
        try:
            add_fn = getattr(self._memory_processor, "add_dialogues", None)
            if add_fn is None:
                # Fallback: add one at a time via add_dialogue
                add_single = getattr(self._memory_processor, "add_dialogue", None)
                if add_single is not None:
                    for dlg in dialogues:
                        result = add_single(dlg.speaker, dlg.content, dlg.timestamp)
                        if asyncio.iscoroutine(result):
                            await result
            else:
                result = add_fn(dialogues)
                if asyncio.iscoroutine(result):
                    await result
        except Exception:
            logger.exception(
                "Error feeding dialogues to memory processor for session %s",
                memory_session_id,
            )
            return 0

        # Finalize to produce MemoryEntry objects
        memory_entries: List[Any] = []
        try:
            finalize_fn = getattr(self._memory_processor, "finalize", None)
            if finalize_fn is not None:
                result = finalize_fn()
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, list):
                    memory_entries = result
                else:
                    # Some implementations store entries internally;
                    # try to retrieve them.
                    get_entries = getattr(self._memory_processor, "get_entries", None)
                    if get_entries is not None:
                        result = get_entries()
                        if asyncio.iscoroutine(result):
                            result = await result
                        memory_entries = result or []
        except Exception:
            logger.exception(
                "Error during memory processor finalize for session %s",
                memory_session_id,
            )
            return 0

        if not memory_entries:
            logger.debug(
                "Memory processor produced no entries for session %s", memory_session_id
            )
            return 0

        # Store entries in VectorStore with provenance
        try:
            await self._vector_store.add_entries(
                entries=memory_entries,
                tenant_id=session.tenant_id,
                memory_session_id=memory_session_id,
                source_kind="memory_pipeline",
                source_id=0,
                importance=0.5,
            )
            logger.info(
                "Stored %d memory entries from processor for session %s",
                len(memory_entries),
                memory_session_id,
            )
            return len(memory_entries)
        except Exception:
            logger.exception(
                "Error storing memory entries for session %s",
                memory_session_id,
            )
            return 0

    async def _generate_and_store_summary(
        self,
        memory_session_id: str,
        session: SessionRecord,
        event_count: int,
        observation_count: int,
        entries_stored: int,
    ) -> bool:
        """Build a template-based summary and persist it to storage.

        No LLM calls are made — the summary is purely mechanical.

        Returns ``True`` if the summary was stored successfully.
        """
        request_text = session.user_prompt or "(no prompt recorded)"

        completed_parts: List[str] = []
        completed_parts.append(f"Captured {event_count} events")
        if observation_count:
            completed_parts.append(f"extracted {observation_count} observations")
        if entries_stored:
            completed_parts.append(
                f"produced {entries_stored} memory entries via memory pipeline"
            )
        completed_text = "; ".join(completed_parts) + "."

        await self._storage.store_summary(
            memory_session_id=memory_session_id,
            request=request_text,
            completed=completed_text,
        )
        return True

    @staticmethod
    def _parse_payload(payload_json: Optional[str]) -> Optional[Dict[str, Any]]:
        """Safely deserialise a JSON payload string."""
        if payload_json is None:
            return None
        # Handle dict (already parsed) or string
        if isinstance(payload_json, dict):
            return payload_json
        try:
            data = json.loads(payload_json)
            if isinstance(data, dict):
                return data
            return None
        except (json.JSONDecodeError, TypeError):
            return None

    async def close(self) -> None:
        """Close storage connections."""
        try:
            await self._storage.close()
        except Exception:
            logger.exception("Error closing session storage")
        try:
            await self._vector_store.close()
        except Exception:
            logger.exception("Error closing vector store")