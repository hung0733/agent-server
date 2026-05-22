from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.i18n import t
logger = logging.getLogger(__name__)


def report_metric(event: str, data: dict, instance_id: str | None = None) -> None:
    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if instance_id:
        payload["instance_id"] = instance_id
    payload.update(data)
    logger.info(t("tdai_memory.pipeline.metric"), json.dumps(payload, ensure_ascii=False))
