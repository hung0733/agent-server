"""aiohttp web application for health, dashboard APIs, and SPA serving."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from api.dashboard import DashboardDataProvider

if TYPE_CHECKING:
    from pathlib import Path


QUEUE_KEY = web.AppKey("queue", object)
DEDUP_KEY = web.AppKey("dedup", object)
DASHBOARD_PROVIDER_KEY = web.AppKey("dashboard_provider", DashboardDataProvider)
FRONTEND_DIST_KEY = web.AppKey("frontend_dist", Path)


async def _health(request: web.Request) -> web.Response:
    queue = request.app[QUEUE_KEY]
    dedup = request.app[DEDUP_KEY]
    queue_size = 0
    if hasattr(queue, "qsize"):
        queue_size = queue.qsize()
    elif hasattr(queue, "get_stats"):
        stats = await queue.get_stats()
        queue_size = int(getattr(stats, "pending_tasks", 0))
    body = {
        "status": "ok",
        "queue_size": queue_size,
        "dedup_tracked": dedup.size,
    }
    return web.Response(
        text=json.dumps(body), content_type="application/json", status=200
    )


async def _dashboard_overview(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    return web.json_response(await provider.get_overview())


async def _dashboard_usage(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    return web.json_response(await provider.get_usage())


async def _dashboard_agents(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    return web.json_response(await provider.get_agents())


async def _dashboard_tasks(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    return web.json_response(await provider.get_tasks())


async def _dashboard_memory(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    return web.json_response(await provider.get_memory())


async def _dashboard_settings(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    return web.json_response(await provider.get_settings())


def _default_frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def _spa_entry(request: web.Request) -> web.StreamResponse:
    frontend_dist = request.app.get(FRONTEND_DIST_KEY)
    if frontend_dist is None:
        raise web.HTTPNotFound(text="Frontend build not found")
    return web.FileResponse(frontend_dist / "index.html")


def create_app(
    queue,
    dedup,
    dashboard_data_provider: DashboardDataProvider | None = None,
    frontend_dist: Path | None = None,
) -> web.Application:
    """Create and configure the aiohttp Application.

    Args:
        queue: Shared queue instance (for stats).
        dedup: Shared deduplicator instance (for stats).
        dashboard_data_provider: Optional provider for dashboard payloads.
        frontend_dist: Optional built frontend dist directory.

    Returns:
        Configured aiohttp.web.Application ready to run.
    """
    app = web.Application()
    app[QUEUE_KEY] = queue
    app[DEDUP_KEY] = dedup
    app[DASHBOARD_PROVIDER_KEY] = dashboard_data_provider or DashboardDataProvider(queue, dedup)
    app.router.add_get("/health", _health)

    app.router.add_get("/api/dashboard/overview", _dashboard_overview)
    app.router.add_get("/api/dashboard/usage", _dashboard_usage)
    app.router.add_get("/api/dashboard/agents", _dashboard_agents)
    app.router.add_get("/api/dashboard/tasks", _dashboard_tasks)
    app.router.add_get("/api/dashboard/memory", _dashboard_memory)
    app.router.add_get("/api/dashboard/settings", _dashboard_settings)

    dist_path = frontend_dist or _default_frontend_dist()
    if dist_path.exists():
        app[FRONTEND_DIST_KEY] = dist_path
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.router.add_static("/assets", assets_path)
        app.router.add_get("/", _spa_entry)
        app.router.add_get(r"/{tail:(?!api|health|assets).*$}", _spa_entry)
    return app
