"""Gettext i18n setup for agent-server.

Default locale: zh-HK (香港繁體中文).
Falls back to the original string if no translation is found.

Usage in any module:
    from i18n import _
    logger.info(_("Some log message: %s"), value)
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
_DOMAIN = "agent_server"
_DEFAULT_LANG = os.getenv("LANG_LOCALE", "zh_HK")

_translation = gettext.translation(
    domain=_DOMAIN,
    localedir=str(_LOCALE_DIR),
    languages=[_DEFAULT_LANG],
    fallback=True,  # Return original string if .mo not found
)

_ = _translation.gettext
