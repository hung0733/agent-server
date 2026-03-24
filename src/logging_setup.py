"""Logging configuration for agent-server.

Sets up two handlers:
  - Console (stdout) — INFO and above
  - Daily rotating file — INFO and above, one file per day

File pattern: /mnt/data/misc/agent-server/log/agent-server.YYYY-MM-DD.log
Rotated files are kept for LOG_RETENTION_DAYS (default 30) days.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from i18n import _

_LOG_DIR = Path(os.getenv("LOG_DIR", "/mnt/data/misc/agent-server/log"))
_LOG_FILE = _LOG_DIR / "agent-server.log"
_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with console + daily rotating file handlers.

    Safe to call multiple times — handlers are only added once.

    Args:
        level: Logging level for both handlers (default INFO).
    """
    root = logging.getLogger()

    # Avoid adding duplicate handlers on re-import / re-call
    if root.handlers:
        return

    root.setLevel(level)
    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Daily rotating file handler
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=_LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=_RETENTION_DAYS,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Rename rotated files from agent-server.log.YYYY-MM-DD
    # to agent-server.YYYY-MM-DD.log for clarity
    def _namer(default_name: str) -> str:
        base, _, suffix = default_name.rpartition(".")
        # default_name is like: .../agent-server.log.2025-03-24
        # We want:              .../agent-server.2025-03-24.log
        stem = base.removesuffix(".log")
        return f"{stem}.{suffix}.log"

    file_handler.namer = _namer
    root.addHandler(file_handler)

    logging.getLogger(__name__).info(
        _("Logging initialised — files: %s"), _LOG_DIR
    )
