# pyright: reportMissingImports=false
"""
SimpleMem-Cross-Lite: Lightweight cross-conversation memory utilities.

This package provides simplified cross-session memory capabilities
for SimpleMem with minimal dependencies.
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "SimpleMem Team"

# Use absolute imports to support pytest collection
try:
    from simplemem_cross_lite.types import (
        MemoryEntry,
        SessionRecord,
        SessionEvent,
        CrossObservation,
        SessionSummary,
        SessionStatus,
        EventKind,
        ObservationType,
        RedactionLevel,
        MemoryLink,
        CrossMemoryEntry,
        ContextBundle,
        FinalizationReport,
        ConsolidationRun,
    )
except ImportError:
    # Fallback to relative imports when not installed as package
    from .types import (
        MemoryEntry,
        SessionRecord,
        SessionEvent,
        CrossObservation,
        SessionSummary,
        SessionStatus,
        EventKind,
        ObservationType,
        RedactionLevel,
        MemoryLink,
        CrossMemoryEntry,
        ContextBundle,
        FinalizationReport,
        ConsolidationRun,
    )

__all__ = [
    "__version__",
    "__author__",
    "MemoryEntry",
    "SessionRecord",
    "SessionEvent",
    "CrossObservation",
    "SessionSummary",
    "SessionStatus",
    "EventKind",
    "ObservationType",
    "RedactionLevel",
    "MemoryLink",
    "CrossMemoryEntry",
    "ContextBundle",
    "FinalizationReport",
    "ConsolidationRun",
]
