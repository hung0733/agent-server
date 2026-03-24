"""aiohttp web application — health / admin endpoints.

Not used for receiving channel events (those arrive via WebSocket).
Exposes operational metrics for monitoring.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from msg_queue.message_queue import MessageQueue
    from msg_queue.dedup import MessageDeduplicator


async def _health(request: web.Request) -> web.Response:
    queue: MessageQueue = request.app["queue"]
    dedup: MessageDeduplicator = request.app["dedup"]
    body = {
        "status": "ok",
        "queue_size": queue.qsize(),
        "dedup_tracked": dedup.size,
    }
    return web.Response(
        text=json.dumps(body), content_type="application/json", status=200
    )


def create_app(queue: MessageQueue, dedup: MessageDeduplicator) -> web.Application:
    """Create and configure the aiohttp Application.

    Args:
        queue: Shared MessageQueue instance (for stats).
        dedup: Shared MessageDeduplicator instance (for stats).

    Returns:
        Configured aiohttp.web.Application ready to run.
    """
    app = web.Application()
    app["queue"] = queue
    app["dedup"] = dedup
    app.router.add_get("/health", _health)
    return app
