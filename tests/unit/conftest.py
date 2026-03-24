"""Shared fixtures for unit tests (no DB required)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
