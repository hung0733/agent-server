"""
Abstract base classes for storage interfaces.

This module defines the contracts for session and vector storage implementations.
"""

from abc import ABC, abstractmethod
from typing import Optional

from simplemem_cross_lite.types import (
    SessionRecord,
    SessionEvent,
    CrossObservation,
    SessionSummary,
    CrossMemoryEntry,
    EventKind,
    ObservationType,
    RedactionLevel,
    SessionStatus,
)


class SessionStorage(ABC):
    """
    Abstract interface for session storage.
    
    Manages session lifecycle, events, observations, and summaries.
    """

    @abstractmethod
    def create_session(
        self,
        tenant_id: str,
        content_session_id: str,
        project: str,
        user_prompt: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> SessionRecord:
        """Create a new session record."""
        pass

    @abstractmethod
    def get_session_by_content_id(
        self, content_session_id: str
    ) -> Optional[SessionRecord]:
        """Retrieve session by content session ID."""
        pass

    @abstractmethod
    def get_session_by_memory_id(
        self, memory_session_id: str
    ) -> Optional[SessionRecord]:
        """Retrieve session by memory session ID."""
        pass

    @abstractmethod
    def get_session_by_id(self, session_id: int) -> Optional[SessionRecord]:
        """Retrieve session by database ID."""
        pass

    @abstractmethod
    def update_session_status(
        self,
        memory_session_id: str,
        status: SessionStatus,
        ended_at: Optional[str] = None,
    ) -> None:
        """Update session status and optionally set end time."""
        pass

    @abstractmethod
    def list_sessions(
        self,
        tenant_id: Optional[str] = None,
        project: Optional[str] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionRecord]:
        """List sessions with optional filters."""
        pass

    @abstractmethod
    def add_event(
        self,
        memory_session_id: str,
        kind: EventKind,
        title: Optional[str] = None,
        payload_json: Optional[dict[str, object]] = None,
        redaction_level: Optional[RedactionLevel] = None,
    ) -> int:
        """Add an event to a session."""
        pass

    @abstractmethod
    def get_events_for_session(
        self,
        memory_session_id: str,
        kinds: Optional[list[EventKind]] = None,
    ) -> list[SessionEvent]:
        """Retrieve events for a session."""
        pass

    @abstractmethod
    def store_observation(
        self,
        memory_session_id: str,
        type: ObservationType,
        title: str,
        subtitle: Optional[str] = None,
        facts_json: Optional[dict[str, object]] = None,
        narrative: Optional[str] = None,
        concepts_json: Optional[list[str]] = None,
        files_json: Optional[list[str]] = None,
        vector_ref: Optional[str] = None,
    ) -> int:
        """Store an observation extracted from a session."""
        pass

    @abstractmethod
    def get_observations_for_session(
        self, memory_session_id: str
    ) -> list[CrossObservation]:
        """Retrieve observations for a session."""
        pass

    @abstractmethod
    def get_recent_observations(
        self,
        project: str,
        limit: int = 50,
        types: Optional[list[ObservationType]] = None,
    ) -> list[CrossObservation]:
        """Get recent observations for a project."""
        pass

    @abstractmethod
    def get_observations_by_ids(self, obs_ids: list[int]) -> list[CrossObservation]:
        """Get observations by IDs."""
        pass

    @abstractmethod
    def store_summary(
        self,
        memory_session_id: str,
        request: Optional[str] = None,
        investigated: Optional[str] = None,
        learned: Optional[str] = None,
        completed: Optional[str] = None,
        next_steps: Optional[str] = None,
        vector_ref: Optional[str] = None,
    ) -> int:
        """Store a session summary."""
        pass

    @abstractmethod
    def get_summary_for_session(
        self, memory_session_id: str
    ) -> Optional[SessionSummary]:
        """Retrieve summary for a session."""
        pass

    @abstractmethod
    def get_recent_summaries(
        self, project: str, limit: int = 10
    ) -> list[SessionSummary]:
        """Get recent summaries for a project."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the storage and release resources."""
        pass


class VectorStore(ABC):
    """
    Abstract interface for vector storage.
    
    Manages memory entry embeddings and supports semantic/keyword search.
    """

    @abstractmethod
    def add_entries(
        self,
        entries: list[CrossMemoryEntry],
        tenant_id: str,
        memory_session_id: str,
        source_kind: str,
        source_id: int = 0,
        importance: float = 0.5,
    ) -> None:
        """Batch add memory entries to the vector store."""
        pass

    @abstractmethod
    def semantic_search(
        self,
        query: str,
        top_k: int = 25,
        tenant_id: Optional[str] = None,
        project: Optional[str] = None,
    ) -> list[CrossMemoryEntry]:
        """Search entries by semantic similarity."""
        pass

    @abstractmethod
    def keyword_search(
        self,
        keywords: list[str],
        top_k: int = 5,
        tenant_id: Optional[str] = None,
    ) -> list[CrossMemoryEntry]:
        """Search entries by keyword matching (BM25)."""
        pass

    @abstractmethod
    def structured_search(
        self,
        persons: Optional[list[str]] = None,
        timestamp_range: Optional[tuple] = None,
        location: Optional[str] = None,
        entities: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[CrossMemoryEntry]:
        """Search entries by metadata filters."""
        pass

    @abstractmethod
    def get_entries_for_session(
        self, memory_session_id: str
    ) -> list[CrossMemoryEntry]:
        """Get all entries for a specific session."""
        pass

    @abstractmethod
    def get_all_entries(
        self, tenant_id: Optional[str] = None
    ) -> list[CrossMemoryEntry]:
        """Get all entries, optionally filtered by tenant."""
        pass

    @abstractmethod
    def mark_superseded(self, old_entry_id: str, new_entry_id: str) -> None:
        """Mark an entry as superseded by another entry."""
        pass

    @abstractmethod
    def update_importance(self, entry_id: str, new_importance: float) -> None:
        """Update importance score for an entry."""
        pass

    @abstractmethod
    def clear(self, tenant_id: Optional[str] = None) -> None:
        """Clear all entries or entries for a specific tenant."""
        pass

    @abstractmethod
    def optimize(self) -> None:
        """Optimize the vector store for better query performance."""
        pass

    @abstractmethod
    def count_entries(
        self, tenant_id: Optional[str] = None, memory_session_id: Optional[str] = None
    ) -> int:
        """Count entries with optional filters."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the vector store and release resources."""
        pass
