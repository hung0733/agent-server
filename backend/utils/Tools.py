from __future__ import annotations

import os

from backend.i18n import t


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(t("llm.missing_config") % name)
    return value
