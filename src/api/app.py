"""aiohttp web application for health, dashboard APIs, and SPA serving."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from aiohttp import web

from api.auth import DashboardAuthService
from api.dashboard import DashboardDataProvider
from db.crypto import CryptoManager
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from db.dao.llm_endpoint_group_dao import LLMEndpointGroupDAO
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dto.llm_endpoint_dto import LLMEndpointCreate, LLMEndpointUpdate, LLMLevelEndpointCreate

if TYPE_CHECKING:
    from pathlib import Path


QUEUE_KEY = web.AppKey("queue", object)
DEDUP_KEY = web.AppKey("dedup", object)
DASHBOARD_PROVIDER_KEY = web.AppKey("dashboard_provider", DashboardDataProvider)
FRONTEND_DIST_KEY = web.AppKey("frontend_dist", Path)
AUTH_SERVICE_KEY = web.AppKey("auth_service", DashboardAuthService)
AUTH_CONTEXT_KEY = web.AppKey("auth_context", dict)


async def _require_auth(request: web.Request) -> dict:
    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "unauthorized"}),
            content_type="application/json",
        )

    auth_service = request.app[AUTH_SERVICE_KEY]
    auth_context = await auth_service.authenticate(raw_key)
    if auth_context is None:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "unauthorized"}),
            content_type="application/json",
        )

    request[AUTH_CONTEXT_KEY] = auth_context
    return auth_context


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
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_overview(user_id=auth_context["user_id"]))


async def _dashboard_usage(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_usage(user_id=auth_context["user_id"]))


async def _dashboard_agents(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_agents(user_id=auth_context["user_id"]))


async def _dashboard_tasks(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_tasks(user_id=auth_context["user_id"]))


async def _dashboard_memory(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_memory(user_id=auth_context["user_id"]))


async def _dashboard_settings(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_settings(user_id=auth_context["user_id"]))


def _serialize_endpoint(endpoint) -> dict:
    return {
        "id": str(endpoint.id),
        "name": endpoint.name,
        "baseUrl": endpoint.base_url,
        "modelName": endpoint.model_name,
        "isActive": endpoint.is_active,
        "apiKeyConfigured": bool(getattr(endpoint, "api_key_encrypted", "")),
    }


async def _settings_create_endpoint(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()
    encrypted_key = CryptoManager().encrypt(body["apiKey"]) if body.get("apiKey") else ""
    endpoint = await LLMEndpointDAO.create(
        LLMEndpointCreate(
            user_id=auth_context["user_id"],
            name=body["name"],
            base_url=body["baseUrl"],
            api_key_encrypted=encrypted_key,
            model_name=body["modelName"],
            config_json=body.get("configJson"),
            is_active=body.get("isActive", True),
        )
    )
    return web.json_response({"endpoint": _serialize_endpoint(endpoint)})


async def _settings_update_endpoint(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    endpoint_id = UUID(request.match_info["endpoint_id"])
    existing = await LLMEndpointDAO.get_by_id(endpoint_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()

    body = await request.json()
    update_kwargs = {
        "id": endpoint_id,
        "name": body.get("name"),
        "base_url": body.get("baseUrl"),
        "model_name": body.get("modelName"),
        "config_json": body.get("configJson"),
        "is_active": body.get("isActive"),
    }
    if body.get("apiKey"):
        update_kwargs["api_key_encrypted"] = CryptoManager().encrypt(body["apiKey"])
    endpoint = await LLMEndpointDAO.update(LLMEndpointUpdate(**update_kwargs))
    if endpoint is None:
        raise web.HTTPNotFound()
    return web.json_response({"endpoint": _serialize_endpoint(endpoint)})


async def _settings_delete_endpoint(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    endpoint_id = UUID(request.match_info["endpoint_id"])
    existing = await LLMEndpointDAO.get_by_id(endpoint_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    assignment = await LLMLevelEndpointDAO.get_by_endpoint_id(endpoint_id)
    if assignment is not None:
        raise web.HTTPConflict(
            text=json.dumps({"error": "endpoint_in_use"}),
            content_type="application/json",
        )
    await LLMEndpointDAO.delete(endpoint_id)
    return web.json_response({"deleted": True})


async def _settings_put_mapping(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()
    group_id = UUID(body["groupId"])
    endpoint_id = UUID(body["endpointId"]) if body.get("endpointId") else None
    group = await LLMEndpointGroupDAO.get_by_id(group_id)
    if group is None or group.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    if endpoint_id is not None:
        endpoint = await LLMEndpointDAO.get_by_id(endpoint_id)
        if endpoint is None or endpoint.user_id != auth_context["user_id"]:
            raise web.HTTPNotFound()

    rows = await LLMLevelEndpointDAO.get_by_group_id(group_id)
    matching = [
        row
        for row in rows
        if row.difficulty_level == int(body["difficultyLevel"])
        and row.involves_secrets is bool(body["involvesSecrets"])
    ]
    if endpoint_id is None:
        for row in matching:
            await LLMLevelEndpointDAO.delete(row.id)
        return web.json_response({"mapping": None})

    existing_for_endpoint = await LLMLevelEndpointDAO.get_by_endpoint_id(endpoint_id)
    if existing_for_endpoint is not None and all(existing_for_endpoint.id != row.id for row in matching):
        await LLMLevelEndpointDAO.delete(existing_for_endpoint.id)

    for row in matching:
        await LLMLevelEndpointDAO.delete(row.id)

    created = await LLMLevelEndpointDAO.create(
        LLMLevelEndpointCreate(
            group_id=group_id,
            endpoint_id=endpoint_id,
            difficulty_level=int(body["difficultyLevel"]),
            involves_secrets=bool(body["involvesSecrets"]),
            priority=int(body.get("priority", 0)),
            is_active=True,
        )
    )
    return web.json_response(
        {
            "mapping": {
                "id": str(created.id),
                "difficultyLevel": created.difficulty_level,
                "involvesSecrets": created.involves_secrets,
                "endpointId": str(created.endpoint_id),
                "priority": created.priority,
                "isActive": created.is_active,
            }
        }
    )


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
    auth_service: DashboardAuthService | None = None,
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
    app[AUTH_SERVICE_KEY] = auth_service or DashboardAuthService()
    app.router.add_get("/health", _health)

    app.router.add_get("/api/dashboard/overview", _dashboard_overview)
    app.router.add_get("/api/dashboard/usage", _dashboard_usage)
    app.router.add_get("/api/dashboard/agents", _dashboard_agents)
    app.router.add_get("/api/dashboard/tasks", _dashboard_tasks)
    app.router.add_get("/api/dashboard/memory", _dashboard_memory)
    app.router.add_get("/api/dashboard/settings", _dashboard_settings)
    app.router.add_post("/api/dashboard/settings/endpoints", _settings_create_endpoint)
    app.router.add_patch("/api/dashboard/settings/endpoints/{endpoint_id}", _settings_update_endpoint)
    app.router.add_delete("/api/dashboard/settings/endpoints/{endpoint_id}", _settings_delete_endpoint)
    app.router.add_put("/api/dashboard/settings/mappings", _settings_put_mapping)

    dist_path = frontend_dist or _default_frontend_dist()
    if dist_path.exists():
        app[FRONTEND_DIST_KEY] = dist_path
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.router.add_static("/assets", assets_path)
        app.router.add_get("/", _spa_entry)
        app.router.add_get(r"/{tail:(?!api|health|assets).*$}", _spa_entry)
    return app
