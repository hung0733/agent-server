"""aiohttp web application for health, dashboard APIs, and SPA serving."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import secrets
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime

from aiohttp import web
from sqlalchemy.exc import IntegrityError

from api.auth import DashboardAuthService
from api.auth import hash_api_key
from i18n import _

logger = logging.getLogger(__name__)
from api.dashboard import DashboardDataProvider
from db.dao.api_key_dao import APIKeyDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_tool_dao import AgentInstanceToolDAO
from db.crypto import CryptoManager
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from db.dao.llm_endpoint_group_dao import LLMEndpointGroupDAO
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dao.tool_dao import ToolDAO
from db.dto.llm_endpoint_dto import LLMEndpointCreate, LLMEndpointUpdate, LLMLevelEndpointCreate
from db.dto.agent_tool_dto import AgentInstanceToolCreate, AgentInstanceToolUpdate
from db.dto.user_dto import APIKeyCreate, APIKeyUpdate
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dto.agent_dto import AgentTypeCreate, AgentTypeUpdate, AgentInstanceCreate, AgentInstanceUpdate
from db.dao.memory_block_dao import MemoryBlockDAO
from db.dto.memory_block_dto import MemoryBlockCreate, MemoryBlockUpdate
from db.dto.collaboration_dto import CollaborationSessionCreate
from db.types import CollaborationStatus


def _parse_optional_datetime(value):
    if not value:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value

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


async def _upsert_memory_blocks(agent_instance_id: UUID, memory_blocks: dict) -> None:
    """Create or update memory blocks for an agent instance.

    Only processes non-empty content values. Matches existing blocks by
    memory_type and updates them; creates new blocks when none exist.
    """
    if not memory_blocks:
        return
    existing = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance_id)
    existing_by_type = {b.memory_type: b for b in existing}
    for mem_type, content in memory_blocks.items():
        if not content:
            continue
        if mem_type in existing_by_type:
            await MemoryBlockDAO.update(
                MemoryBlockUpdate(id=existing_by_type[mem_type].id, content=content)
            )
        else:
            await MemoryBlockDAO.create(
                MemoryBlockCreate(
                    agent_instance_id=agent_instance_id,
                    memory_type=mem_type,
                    content=content,
                )
            )


async def _agents_create(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()

    agent_type_id = UUID(body["agentTypeId"])
    existing_type = await AgentTypeDAO.get_by_id(agent_type_id)
    if existing_type is None or existing_type.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_type_not_found"}),
            content_type="application/json",
        )

    raw_endpoint_group_id = body.get("endpointGroupId")
    endpoint_group_id = UUID(raw_endpoint_group_id) if raw_endpoint_group_id else None

    uuid_value = uuid4()

    agent = await AgentInstanceDAO.create(
        AgentInstanceCreate(
            agent_type_id=agent_type_id,
            user_id=auth_context["user_id"],
            name=body.get("name"),
            agent_id=f"agent-{uuid_value}",
            phone_no=body.get("phoneNo"),
            whatsapp_key=body.get("whatsappKey"),
            is_sub_agent=body.get("isSubAgent", False),
            is_active=body.get("isActive", True),
            status=body.get("status", "idle"),
            endpoint_group_id=endpoint_group_id,
        )
    )

    await CollaborationSessionDAO.create(
        CollaborationSessionCreate(
            user_id=auth_context["user_id"],
            main_agent_id=agent.id,
            session_id=f"default-{uuid_value}",
            name=_("預設對話"),
            status=CollaborationStatus.active,
        )
    )

    await CollaborationSessionDAO.create(
        CollaborationSessionCreate(
            user_id=auth_context["user_id"],
            main_agent_id=agent.id,
            session_id=f"ghost-{uuid_value}",
            name=_("心靈對話"),
            status=CollaborationStatus.active,
        )
    )

    await _upsert_memory_blocks(agent.id, body.get("memoryBlocks") or {})

    return web.json_response({"agent": _serialize_agent_instance(agent)}, status=201)


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


async def _dashboard_agent_tools(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_agent_tools(user_id=auth_context["user_id"]))


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


def _serialize_agent_type(at) -> dict:
    return {
        "id": str(at.id),
        "name": at.name,
        "description": at.description,
        "isActive": at.is_active,
        "createdAt": at.created_at.isoformat() if at.created_at else None,
    }


def _serialize_agent_instance(agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "agentTypeId": str(agent.agent_type_id) if agent.agent_type_id else None,
        "status": agent.status,
        "phoneNo": agent.phone_no,
        "whatsappKey": agent.whatsapp_key,
        "isSubAgent": agent.is_sub_agent,
        "isActive": agent.is_active,
        "agentId": agent.agent_id,
        "endpointGroupId": str(agent.endpoint_group_id) if agent.endpoint_group_id else None,
        "createdAt": agent.created_at.isoformat() if agent.created_at else None,
    }


def _serialize_auth_key(key) -> dict:
    return {
        "id": str(key.id),
        "name": key.name or "未命名 Key",
        "isActive": key.is_active,
        "lastUsedAt": key.last_used_at.isoformat() if key.last_used_at else None,
        "expiresAt": key.expires_at.isoformat() if key.expires_at else None,
        "createdAt": key.created_at.isoformat() if key.created_at else None,
    }


async def _settings_create_auth_key(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()
    raw_key = secrets.token_urlsafe(32)
    key = await APIKeyDAO.create(
        APIKeyCreate(
            user_id=auth_context["user_id"],
            key_hash=hash_api_key(raw_key),
            name=body.get("name"),
            is_active=True,
            expires_at=_parse_optional_datetime(body.get("expiresAt")),
        )
    )
    return web.json_response({"key": _serialize_auth_key(key), "rawKey": raw_key})


async def _settings_update_auth_key(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    key_id = UUID(request.match_info["key_id"])
    existing = await APIKeyDAO.get_by_id(key_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    body = await request.json()
    key = await APIKeyDAO.update(
        APIKeyUpdate(
            id=key_id,
            name=body.get("name"),
            is_active=body.get("isActive"),
            expires_at=_parse_optional_datetime(body.get("expiresAt")),
        )
    )
    if key is None:
        raise web.HTTPNotFound()
    return web.json_response({"key": _serialize_auth_key(key)})


async def _settings_delete_auth_key(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    key_id = UUID(request.match_info["key_id"])
    existing = await APIKeyDAO.get_by_id(key_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    await APIKeyDAO.delete(key_id)
    return web.json_response({"deleted": True})


async def _settings_regenerate_auth_key(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    key_id = UUID(request.match_info["key_id"])
    existing = await APIKeyDAO.get_by_id(key_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()

    await APIKeyDAO.update(APIKeyUpdate(id=key_id, is_active=False))
    body = await request.json()
    raw_key = secrets.token_urlsafe(32)
    key = await APIKeyDAO.create(
        APIKeyCreate(
            user_id=auth_context["user_id"],
            key_hash=hash_api_key(raw_key),
            name=body.get("name") or existing.name,
            is_active=True,
            expires_at=_parse_optional_datetime(body.get("expiresAt")) if "expiresAt" in body else existing.expires_at,
        )
    )
    return web.json_response({"key": _serialize_auth_key(key), "rawKey": raw_key})


async def _agent_types_list(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    items = await AgentTypeDAO.get_all(user_id=auth_context["user_id"])
    return web.json_response({"agentTypes": [_serialize_agent_type(i) for i in items]})


async def _agent_types_create(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()
    try:
        agent_type = await AgentTypeDAO.create(
            AgentTypeCreate(
                user_id=auth_context["user_id"],
                name=body["name"],
                description=body.get("description"),
                is_active=body.get("isActive", True),
            )
        )
    except IntegrityError:
        raise web.HTTPConflict(
            text=json.dumps({"error": "name_already_exists"}),
            content_type="application/json",
        )
    return web.json_response({"agentType": _serialize_agent_type(agent_type)}, status=201)


async def _agent_types_update(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_type_id = UUID(request.match_info["agent_type_id"])
    existing = await AgentTypeDAO.get_by_id(agent_type_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    body = await request.json()
    updated = await AgentTypeDAO.update(
        AgentTypeUpdate(
            id=agent_type_id,
            name=body.get("name"),
            description=body.get("description"),
            is_active=body.get("isActive"),
        )
    )
    if updated is None:
        raise web.HTTPNotFound()
    return web.json_response({"agentType": _serialize_agent_type(updated)})


async def _agent_types_delete(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_type_id = UUID(request.match_info["agent_type_id"])
    existing = await AgentTypeDAO.get_by_id(agent_type_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()
    await AgentTypeDAO.delete(agent_type_id)
    return web.json_response({"deleted": True})


async def _agent_tool_update(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_id = UUID(request.match_info["agent_id"])
    tool_id = UUID(request.match_info["tool_id"])

    agent = await AgentInstanceDAO.get_by_id(agent_id)
    if agent is None or agent.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()

    tool = await ToolDAO.get_by_id(tool_id)
    if tool is None:
        raise web.HTTPNotFound()

    body = await request.json()
    is_enabled = bool(body.get("isEnabled", True))

    overrides = await AgentInstanceToolDAO.get_overrides_for_instance(agent_id)
    existing = next((override for override in overrides if override.tool_id == tool_id), None)

    if existing is None:
        updated = await AgentInstanceToolDAO.assign(
            AgentInstanceToolCreate(
                agent_instance_id=agent_id,
                tool_id=tool_id,
                is_enabled=is_enabled,
            )
        )
    else:
        updated = await AgentInstanceToolDAO.update(
            AgentInstanceToolUpdate(id=existing.id, is_enabled=is_enabled)
        )

    if updated is None:
        raise web.HTTPNotFound()

    return web.json_response(
        {
            "tool": {
                "id": str(updated.id),
                "agentInstanceId": str(updated.agent_instance_id),
                "toolId": str(updated.tool_id),
                "isEnabled": updated.is_enabled,
                "configOverride": updated.config_override,
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
    app.router.add_post("/api/dashboard/agents", _agents_create)
    app.router.add_get("/api/dashboard/tasks", _dashboard_tasks)
    app.router.add_get("/api/dashboard/memory", _dashboard_memory)
    app.router.add_get("/api/dashboard/settings", _dashboard_settings)
    app.router.add_get("/api/dashboard/agents/tools", _dashboard_agent_tools)
    app.router.add_post("/api/dashboard/settings/endpoints", _settings_create_endpoint)
    app.router.add_patch("/api/dashboard/settings/endpoints/{endpoint_id}", _settings_update_endpoint)
    app.router.add_delete("/api/dashboard/settings/endpoints/{endpoint_id}", _settings_delete_endpoint)
    app.router.add_put("/api/dashboard/settings/mappings", _settings_put_mapping)
    app.router.add_post("/api/dashboard/settings/auth-keys", _settings_create_auth_key)
    app.router.add_patch("/api/dashboard/settings/auth-keys/{key_id}", _settings_update_auth_key)
    app.router.add_delete("/api/dashboard/settings/auth-keys/{key_id}", _settings_delete_auth_key)
    app.router.add_post("/api/dashboard/settings/auth-keys/{key_id}/regenerate", _settings_regenerate_auth_key)
    app.router.add_patch("/api/dashboard/agents/{agent_id}/tools/{tool_id}", _agent_tool_update)
    app.router.add_get("/api/dashboard/agent-types", _agent_types_list)
    app.router.add_post("/api/dashboard/agent-types", _agent_types_create)
    app.router.add_patch("/api/dashboard/agent-types/{agent_type_id}", _agent_types_update)
    app.router.add_delete("/api/dashboard/agent-types/{agent_type_id}", _agent_types_delete)

    dist_path = frontend_dist or _default_frontend_dist()
    if dist_path.exists():
        app[FRONTEND_DIST_KEY] = dist_path
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.router.add_static("/assets", assets_path)
        app.router.add_get("/", _spa_entry)
        app.router.add_get(r"/{tail:(?!api|health|assets).*$}", _spa_entry)
    return app
