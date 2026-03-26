"""
Data models for SimpleMem

- Dialogue: Raw dialogue entry
- MemoryEntry: Compressed memory entry with multi-view indexing
"""

from .memory_entry import Dialogue, MemoryEntry

__all__ = ["Dialogue", "MemoryEntry"]
