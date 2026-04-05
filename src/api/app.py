"""aiohttp web application for health, dashboard APIs, and SPA serving."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import secrets
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy.exc import IntegrityError

from api.auth import DashboardAuthService
from api.auth import hash_api_key
from api.new_agent_bootstrap import (
    NEW_AGENT_MODE_REMINDERS,
    build_mode_prompt,
    extract_soul_draft,
    run_new_agent_bootstrap_turn,
)
from i18n import _

logger = logging.getLogger(__name__)
from api.dashboard import DashboardDataProvider
from db.dao.api_key_dao import APIKeyDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_tool_dao import AgentInstanceToolDAO, AgentTypeToolDAO
from db.crypto import CryptoManager
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from db.dao.llm_endpoint_group_dao import LLMEndpointGroupDAO
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dao.tool_dao import ToolDAO
from db.dto.llm_endpoint_dto import LLMEndpointCreate, LLMEndpointUpdate, LLMLevelEndpointCreate
from db.dto.agent_tool_dto import AgentInstanceToolCreate, AgentInstanceToolUpdate, AgentTypeToolCreate, AgentTypeToolUpdate
from db.dto.user_dto import APIKeyCreate, APIKeyUpdate
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dto.agent_dto import AgentTypeCreate, AgentTypeUpdate, AgentInstanceCreate, AgentInstanceUpdate
from db.dao.memory_block_dao import MemoryBlockDAO
from db.dto.memory_block_dto import MemoryBlockCreate, MemoryBlockUpdate
from db.dto.collaboration_dto import CollaborationSessionCreate
from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dto.task_dto import TaskCreate, TaskUpdate
from db.dto.task_schedule_dto import TaskScheduleCreate, TaskScheduleUpdate
from db.types import CollaborationStatus, TaskStatus, Priority, ScheduleType
from db import AsyncSession, async_sessionmaker, create_engine
from scheduler.task_scheduler import calculate_next_run
from sandbox.cleanup import run_sandbox_janitor_forever, run_sandbox_janitor_once
from sandbox.factory import get_sandbox_provider
from utils.timezone import to_server_tz


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
SANDBOX_JANITOR_TASK_KEY = web.AppKey("sandbox_janitor_task", object)


def _sandbox_enabled() -> bool:
    return bool(__import__("os").environ.get("SANDBOX_BACKEND"))


async def _start_sandbox_janitor(app: web.Application) -> None:
    if not _sandbox_enabled():
        return
    idle_timeout = int(__import__("os").environ["SANDBOX_IDLE_TIMEOUT_SECONDS"])
    provider = get_sandbox_provider()
    try:
        await run_sandbox_janitor_once(provider, idle_timeout)
    except Exception as exc:
        logger.warning("sandbox.janitor.startup_cleanup_failed error=%s", exc)
    app[SANDBOX_JANITOR_TASK_KEY] = asyncio.create_task(
        run_sandbox_janitor_forever(provider, idle_timeout)
    )
    logger.info("sandbox.janitor.start idle_timeout_seconds=%s", idle_timeout)


async def _stop_sandbox_janitor(app: web.Application) -> None:
    task = app.get(SANDBOX_JANITOR_TASK_KEY)
    if task is None:
        return
    task.cancel()
    with __import__("contextlib").suppress(asyncio.CancelledError):
        await task
    logger.info("sandbox.janitor.stop")


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


async def _upsert_memory_blocks(
    agent_instance_id: UUID,
    memory_blocks: dict,
    session: Optional[AsyncSession] = None,
) -> None:
    """Create or update memory blocks for an agent instance.

    Only processes non-empty content values. Matches existing blocks by
    memory_type and updates them; creates new blocks when none exist.
    """
    if not memory_blocks:
        return
    existing = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance_id, session=session)
    existing_by_type = {b.memory_type: b for b in existing}
    for mem_type, content in memory_blocks.items():
        if not content:
            continue
        if mem_type in existing_by_type:
            await MemoryBlockDAO.update(
                MemoryBlockUpdate(id=existing_by_type[mem_type].id, content=content),
                session=session,
            )
        else:
            await MemoryBlockDAO.create(
                MemoryBlockCreate(
                    agent_instance_id=agent_instance_id,
                    memory_type=mem_type,
                    content=content,
                ),
                session=session,
            )


_DEFAULT_SCHEDULES = [
    {
        "task_type": "scheduled_method",
        "method_path": "agent.bulter@Bulter.review_ltm",
        "cron": "0 16 * * *",   # 00:00 UTC+8 daily
        "description": "Daily Long-Term Memory Review",
    },
    {
        "task_type": "scheduled_method",
        "method_path": "agent.bulter@Bulter.review_msg",
        "cron": "0 17 * * *",   # 01:00 UTC+8 daily
        "description": "Daily Message Memory Review",
    },
]


async def _create_default_task_schedules(agent, session: AsyncSession) -> None:
    """Create default recurring task schedules for a newly created agent."""
    now = datetime.now(timezone.utc)
    for spec in _DEFAULT_SCHEDULES:
        task = await TaskDAO.create(
            TaskCreate(
                user_id=agent.user_id,
                agent_id=agent.id,
                task_type=spec["task_type"],
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={
                    "task_execution_type": "method",
                    "method_path": spec["method_path"],
                    "description": _(spec["description"]),
                    "agent_instance_id": str(agent.id),
                },
            ),
            session=session,
        )
        next_run = calculate_next_run(spec["cron"], ScheduleType.cron, now)
        await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.cron,
                schedule_expression=spec["cron"],
                is_active=True,
                next_run_at=next_run,
            ),
            session=session,
        )
        logger.info(
            _("[_create_default_task_schedules] 已建立排程: method=%s cron=%s agent=%s"),
            spec["method_path"],
            spec["cron"],
            agent.id,
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
    user_id = auth_context["user_id"]
    agent_id_input = body.get("agentId")
    agent_id_value = agent_id_input if agent_id_input else f"agent-{uuid_value}"

    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as s:
            async with s.begin():
                agent = await AgentInstanceDAO.create(
                    AgentInstanceCreate(
                        agent_type_id=agent_type_id,
                        user_id=user_id,
                        name=body.get("name"),
                        agent_id=agent_id_value,
                        phone_no=body.get("phoneNo"),
                        whatsapp_key=body.get("whatsappKey"),
                        is_sub_agent=body.get("isSubAgent", False),
                        is_active=body.get("isActive", True),
                        status=body.get("status", "idle"),
                        endpoint_group_id=endpoint_group_id,
                    ),
                    session=s,
                )
                await CollaborationSessionDAO.create(
                    CollaborationSessionCreate(
                        user_id=user_id,
                        main_agent_id=agent.id,
                        session_id=f"default-{uuid_value}",
                        name=_("預設對話"),
                        status=CollaborationStatus.active,
                    ),
                    session=s,
                )
                await CollaborationSessionDAO.create(
                    CollaborationSessionCreate(
                        user_id=user_id,
                        main_agent_id=agent.id,
                        session_id=f"ghost-{uuid_value}",
                        name=_("心靈對話"),
                        status=CollaborationStatus.active,
                    ),
                    session=s,
                )
                await _upsert_memory_blocks(agent.id, body.get("memoryBlocks") or {}, session=s)
                await _create_default_task_schedules(agent, session=s)
    finally:
        await engine.dispose()

    agent_type = await AgentTypeDAO.get_by_id(agent.agent_type_id)
    agent_type_name = agent_type.name if agent_type else None
    return web.json_response({"agent": _serialize_agent_instance(agent, agent_type_name)}, status=201)


async def _agents_update(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_instance_id = UUID(request.match_info["agent_id"])
    body = await request.json()

    existing = await AgentInstanceDAO.get_by_id(agent_instance_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    raw_endpoint_group_id = body.get("endpointGroupId")
    endpoint_group_id = UUID(raw_endpoint_group_id) if raw_endpoint_group_id else None

    update_kwargs: dict = {"id": agent_instance_id}
    if "name" in body:
        update_kwargs["name"] = body["name"]
    if "phoneNo" in body:
        update_kwargs["phone_no"] = body["phoneNo"]
    if "whatsappKey" in body:
        update_kwargs["whatsapp_key"] = body["whatsappKey"]
    if "isSubAgent" in body:
        update_kwargs["is_sub_agent"] = body["isSubAgent"]
    if "isActive" in body:
        update_kwargs["is_active"] = body["isActive"]
    if raw_endpoint_group_id is not None:
        update_kwargs["endpoint_group_id"] = endpoint_group_id

    updated = await AgentInstanceDAO.update(AgentInstanceUpdate(**update_kwargs))
    if updated is None:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    await _upsert_memory_blocks(agent_instance_id, body.get("memoryBlocks") or {})

    agent_type = await AgentTypeDAO.get_by_id(updated.agent_type_id)
    agent_type_name = agent_type.name if agent_type else None
    return web.json_response({"agent": _serialize_agent_instance(updated, agent_type_name)})


async def _agents_get_memory_blocks(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_instance_id = UUID(request.match_info["agent_id"])

    existing = await AgentInstanceDAO.get_by_id(agent_instance_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    blocks = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance_id)
    result = {"SOUL": "", "USER_PROFILE": "", "IDENTITY": ""}
    for block in blocks:
        if block.memory_type in result:
            result[block.memory_type] = block.content

    return web.json_response(result)


async def _agents_bootstrap(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    agent_instance_id = UUID(request.match_info["agent_id"])
    body = await request.json()

    existing = await AgentInstanceDAO.get_by_id(agent_instance_id)
    if existing is None or existing.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "agent_not_found"}),
            content_type="application/json",
        )

    save_requested = bool(body.get("save", False))
    message = str(body.get("message") or "").strip()
    history = body.get("history") or []
    if not isinstance(history, list):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "invalid_history"}),
            content_type="application/json",
        )
    if not message and not (save_requested and history):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "message_required"}),
            content_type="application/json",
        )

    mode = "synthesis" if save_requested else str(body.get("mode") or "bootstrap").strip().lower()
    if mode not in NEW_AGENT_MODE_REMINDERS:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "invalid_mode"}),
            content_type="application/json",
        )

    session_id = f"ghost-{existing.agent_id[6:]}"
    memory_blocks = await MemoryBlockDAO.get_by_agent_instance_id(agent_instance_id)
    if body.get("previewPrompt"):
        system_prompt = build_mode_prompt(memory_blocks, mode)
        return web.json_response(
            {
                "sessionId": session_id,
                "mode": mode,
                "message": message,
                "systemPrompt": system_prompt,
                "availableModes": sorted(NEW_AGENT_MODE_REMINDERS.keys()),
            }
        )

    try:
        reply = await run_new_agent_bootstrap_turn(
            agent=existing,
            user_id=auth_context["user_id"],
            mode=mode,
            memory_blocks=memory_blocks,
            history=history,
            message=message,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
        ) from exc
    except Exception as exc:
        logger.error(
            "new agent bootstrap proxy failed: agent=%s mode=%s error=%s",
            existing.id,
            mode,
            exc,
            exc_info=True,
        )
        raise web.HTTPBadGateway(
            text=json.dumps({"error": "bootstrap_llm_failed"}),
            content_type="application/json",
        ) from exc

    if save_requested:
        soul_draft = extract_soul_draft(reply)
        if soul_draft is None:
            logger.error(
                "new agent bootstrap returned invalid soul draft: agent=%s mode=%s reply=%r",
                existing.id,
                mode,
                reply[:500],
            )
            raise web.HTTPBadGateway(
                text=json.dumps({"error": "invalid_soul_draft"}),
                content_type="application/json",
            )

        await _upsert_memory_blocks(agent_instance_id, {"SOUL": soul_draft})
        return web.json_response(
            {
                "sessionId": session_id,
                "mode": "build",
                "reply": _("SOUL saved."),
                "saved": True,
                "soul": soul_draft,
            }
        )

    return web.json_response(
        {
            "sessionId": session_id,
            "mode": mode,
            "reply": reply,
            "saved": False,
        }
    )


async def _dashboard_tasks(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_tasks(user_id=auth_context["user_id"]))


async def _dashboard_memory(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_memory(user_id=auth_context["user_id"]))


async def _dashboard_stm(request: web.Request) -> web.Response:
    """Handle GET /api/dashboard/stm - return STM entries."""
    from api.dashboard_stm import STMDataProvider
    provider = STMDataProvider()
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_stm(user_id=auth_context["user_id"]))


async def _dashboard_ltm(request: web.Request) -> web.Response:
    """Handle GET /api/dashboard/ltm - return LTM entries."""
    from api.dashboard_ltm import LTMDataProvider
    provider = LTMDataProvider()
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_ltm(user_id=auth_context["user_id"]))


async def _dashboard_settings(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_settings(user_id=auth_context["user_id"]))


async def _dashboard_agent_tools(request: web.Request) -> web.Response:
    provider = request.app[DASHBOARD_PROVIDER_KEY]
    auth_context = await _require_auth(request)
    return web.json_response(await provider.get_agent_tools(user_id=auth_context["user_id"]))


def _json_http_error(status: int, error: str) -> web.HTTPException:
    error_map = {
        400: web.HTTPBadRequest,
        404: web.HTTPNotFound,
        409: web.HTTPConflict,
    }
    exc_cls = error_map.get(status, web.HTTPBadRequest)
    return exc_cls(
        text=json.dumps({"error": error}),
        content_type="application/json",
    )


def _normalize_schedule_task_type(task) -> str | None:
    payload = task.payload or {}
    execution_type = payload.get("task_execution_type")
    if execution_type in {"method", "message"}:
        return execution_type

    raw_task_type = str(getattr(task, "task_type", "") or "").lower()
    if "method" in raw_task_type:
        return "method"
    if "message" in raw_task_type:
        return "message"
    return None


def _serialize_schedule_item(schedule, task, agent) -> dict:
    payload = task.payload or {}
    task_type = _normalize_schedule_task_type(task) or "message"
    if task_type == "method":
        prompt = payload.get("method_path") or ""
        fallback_name = payload.get("description") or prompt or "Method schedule"
    else:
        prompt = payload.get("prompt") or ""
        fallback_name = prompt[:40] or "Message schedule"

    agent_name = None
    if agent is not None:
        agent_name = agent.name or agent.agent_id or str(agent.id)

    return {
        "id": str(schedule.id),
        "taskId": str(task.id),
        "taskType": task_type,
        "name": payload.get("name") or fallback_name,
        "prompt": prompt,
        "scheduleType": str(schedule.schedule_type),
        "scheduleExpression": schedule.schedule_expression,
        "isActive": schedule.is_active,
        "nextRunAt": to_server_tz(schedule.next_run_at).isoformat() if schedule.next_run_at else None,
        "lastRunAt": to_server_tz(schedule.last_run_at).isoformat() if schedule.last_run_at else None,
        "agentId": str(task.agent_id) if task.agent_id else None,
        "agentName": agent_name,
    }


async def _load_schedule_context(schedule_id: UUID, user_id) -> tuple:
    schedule = await TaskScheduleDAO.get_by_id(schedule_id)
    if schedule is None:
        raise _json_http_error(404, "schedule_not_found")

    task = await TaskDAO.get_by_id(schedule.task_template_id)
    if task is None or task.user_id != user_id:
        raise _json_http_error(404, "schedule_not_found")

    task_type = _normalize_schedule_task_type(task)
    if task_type is None:
        raise _json_http_error(404, "schedule_not_found")

    agent = None
    if task.agent_id:
        agent = await AgentInstanceDAO.get_by_id(task.agent_id)

    return schedule, task, task_type, agent


def _parse_message_schedule_type(raw_value: str | None) -> ScheduleType:
    if raw_value not in {ScheduleType.cron.value, ScheduleType.interval.value}:
        raise _json_http_error(400, "invalid_schedule_type")
    return ScheduleType(raw_value)


def _require_non_empty_string(body: dict, key: str, error: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _json_http_error(400, error)
    return value.strip()


async def _dashboard_schedules(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    schedules = await TaskScheduleDAO.get_all(limit=500)
    method_schedules: list[dict] = []
    message_schedules: list[dict] = []

    for schedule in schedules:
        task = await TaskDAO.get_by_id(schedule.task_template_id)
        if task is None or task.user_id != auth_context["user_id"]:
            continue

        task_type = _normalize_schedule_task_type(task)
        if task_type is None:
            continue

        agent = None
        if task.agent_id:
            agent = await AgentInstanceDAO.get_by_id(task.agent_id)

        item = _serialize_schedule_item(schedule, task, agent)
        if task_type == "method":
            method_schedules.append(item)
        else:
            message_schedules.append(item)

    method_schedules.sort(key=lambda item: ((item["name"] or "").lower(), item["id"]))
    message_schedules.sort(key=lambda item: ((item["name"] or "").lower(), item["id"]))
    return web.json_response(
        {
            "methodSchedules": method_schedules,
            "messageSchedules": message_schedules,
            "source": "database",
        }
    )


async def _dashboard_create_message_schedule(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    body = await request.json()

    name = _require_non_empty_string(body, "name", "name_required")
    prompt = _require_non_empty_string(body, "prompt", "prompt_required")
    schedule_type = _parse_message_schedule_type(body.get("scheduleType"))
    schedule_expression = _require_non_empty_string(
        body, "scheduleExpression", "schedule_expression_required"
    )
    raw_agent_id = body.get("agentId")
    if not raw_agent_id:
        raise _json_http_error(400, "agent_id_required")

    agent_id = UUID(raw_agent_id)
    agent = await AgentInstanceDAO.get_by_id(agent_id)
    if agent is None or agent.user_id != auth_context["user_id"]:
        raise _json_http_error(404, "agent_not_found")

    try:
        next_run = calculate_next_run(schedule_expression, schedule_type)
        task = await TaskDAO.create(
            TaskCreate(
                user_id=auth_context["user_id"],
                agent_id=agent_id,
                task_type="message",
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={
                    "task_execution_type": "message",
                    "name": name,
                    "prompt": prompt,
                    "system_prompt": "",
                    "think_mode": False,
                },
            )
        )
        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=schedule_type,
                schedule_expression=schedule_expression,
                is_active=bool(body.get("isActive", True)),
                next_run_at=next_run,
            )
        )
    except ValueError as exc:
        raise _json_http_error(400, str(exc)) from exc

    return web.json_response(
        {"schedule": _serialize_schedule_item(schedule, task, agent)}, status=201
    )


async def _dashboard_update_message_schedule(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    schedule_id = UUID(request.match_info["schedule_id"])
    schedule, task, task_type, agent = await _load_schedule_context(
        schedule_id, auth_context["user_id"]
    )
    if task_type != "message":
        raise _json_http_error(400, "schedule_not_editable")

    body = await request.json()
    next_task_payload = dict(task.payload or {})
    payload_changed = False

    if "name" in body:
        next_task_payload["name"] = _require_non_empty_string(body, "name", "name_required")
        payload_changed = True
    if "prompt" in body:
        next_task_payload["prompt"] = _require_non_empty_string(body, "prompt", "prompt_required")
        payload_changed = True

    schedule_type_value = body.get("scheduleType")
    if schedule_type_value is None:
        effective_schedule_type = ScheduleType(str(schedule.schedule_type))
    else:
        effective_schedule_type = _parse_message_schedule_type(schedule_type_value)

    effective_expression = body.get("scheduleExpression", schedule.schedule_expression)
    if not isinstance(effective_expression, str) or not effective_expression.strip():
        raise _json_http_error(400, "schedule_expression_required")
    effective_expression = effective_expression.strip()

    is_active = body.get("isActive", schedule.is_active)

    try:
        next_run = calculate_next_run(effective_expression, effective_schedule_type)
        if payload_changed:
            task = await TaskDAO.update(TaskUpdate(id=task.id, payload=next_task_payload))
            if task is None:
                raise _json_http_error(404, "schedule_not_found")

        updated_schedule = await TaskScheduleDAO.update(
            TaskScheduleUpdate(
                id=schedule.id,
                schedule_type=effective_schedule_type,
                schedule_expression=effective_expression,
                is_active=bool(is_active),
                next_run_at=next_run,
            )
        )
    except ValueError as exc:
        raise _json_http_error(400, str(exc)) from exc

    if updated_schedule is None:
        raise _json_http_error(404, "schedule_not_found")
    return web.json_response(
        {"schedule": _serialize_schedule_item(updated_schedule, task, agent)}
    )


async def _dashboard_delete_message_schedule(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    schedule_id = UUID(request.match_info["schedule_id"])
    schedule, task, task_type, _agent = await _load_schedule_context(
        schedule_id, auth_context["user_id"]
    )
    if task_type != "message":
        raise _json_http_error(400, "schedule_not_editable")

    await TaskScheduleDAO.delete(schedule.id)
    await TaskDAO.delete(task.id)
    return web.json_response({"deleted": True})


async def _dashboard_refresh_message_schedule(request: web.Request) -> web.Response:
    auth_context = await _require_auth(request)
    schedule_id = UUID(request.match_info["schedule_id"])
    schedule, task, task_type, agent = await _load_schedule_context(
        schedule_id, auth_context["user_id"]
    )
    if task_type != "message":
        raise _json_http_error(400, "schedule_not_editable")

    try:
        next_run = calculate_next_run(schedule.schedule_expression, schedule.schedule_type)
        updated_schedule = await TaskScheduleDAO.update(
            TaskScheduleUpdate(id=schedule.id, next_run_at=next_run)
        )
    except ValueError as exc:
        raise _json_http_error(400, str(exc)) from exc

    if updated_schedule is None:
        raise _json_http_error(404, "schedule_not_found")
    return web.json_response(
        {"schedule": _serialize_schedule_item(updated_schedule, task, agent)}
    )


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


def _serialize_agent_instance(agent, agent_type_name: str | None = None) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "agentTypeId": str(agent.agent_type_id) if agent.agent_type_id else None,
        "agentTypeName": agent_type_name,
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


async def _agent_type_tool_update(request: web.Request) -> web.Response:
    """PATCH /api/dashboard/agent-types/{agent_type_id}/tools/{tool_id}"""
    auth_context = await _require_auth(request)
    agent_type_id = UUID(request.match_info["agent_type_id"])
    tool_id = UUID(request.match_info["tool_id"])

    agent_type = await AgentTypeDAO.get_by_id(agent_type_id)
    if agent_type is None or agent_type.user_id != auth_context["user_id"]:
        raise web.HTTPNotFound()

    tool = await ToolDAO.get_by_id(tool_id)
    if tool is None:
        raise web.HTTPNotFound()

    body = await request.json()
    is_active = bool(body.get("isActive", True))

    type_tools = await AgentTypeToolDAO.get_tools_for_type(agent_type_id)
    existing = next((tt for tt in type_tools if tt.tool_id == tool_id), None)

    if existing is None:
        updated = await AgentTypeToolDAO.assign(
            AgentTypeToolCreate(
                agent_type_id=agent_type_id,
                tool_id=tool_id,
                is_active=is_active,
            )
        )
    else:
        updated = await AgentTypeToolDAO.update(
            AgentTypeToolUpdate(id=existing.id, is_active=is_active)
        )

    if updated is None:
        raise web.HTTPNotFound()

    return web.json_response(
        {
            "tool": {
                "id": str(updated.id),
                "agentTypeId": str(updated.agent_type_id),
                "toolId": str(updated.tool_id),
                "isActive": updated.is_active,
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
    app.router.add_post("/api/dashboard/agents/{agent_id}/bootstrap", _agents_bootstrap)
    app.router.add_get("/api/dashboard/tasks", _dashboard_tasks)
    app.router.add_get("/api/dashboard/memory", _dashboard_memory)
    app.router.add_get("/api/dashboard/schedules", _dashboard_schedules)
    app.router.add_post("/api/dashboard/schedules/message", _dashboard_create_message_schedule)
    app.router.add_patch("/api/dashboard/schedules/message/{schedule_id}", _dashboard_update_message_schedule)
    app.router.add_delete("/api/dashboard/schedules/message/{schedule_id}", _dashboard_delete_message_schedule)
    app.router.add_post("/api/dashboard/schedules/message/{schedule_id}/refresh", _dashboard_refresh_message_schedule)
    app.router.add_get("/api/dashboard/stm", _dashboard_stm)
    app.router.add_get("/api/dashboard/ltm", _dashboard_ltm)
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
    app.router.add_patch("/api/dashboard/agents/{agent_id}", _agents_update)
    app.router.add_get("/api/dashboard/agents/{agent_id}/memory-blocks", _agents_get_memory_blocks)
    app.router.add_patch("/api/dashboard/agents/{agent_id}/tools/{tool_id}", _agent_tool_update)
    app.router.add_get("/api/dashboard/agent-types", _agent_types_list)
    app.router.add_post("/api/dashboard/agent-types", _agent_types_create)
    app.router.add_patch("/api/dashboard/agent-types/{agent_type_id}", _agent_types_update)
    app.router.add_delete("/api/dashboard/agent-types/{agent_type_id}", _agent_types_delete)
    app.router.add_patch("/api/dashboard/agent-types/{agent_type_id}/tools/{tool_id}", _agent_type_tool_update)

    dist_path = frontend_dist or _default_frontend_dist()
    if dist_path.exists():
        app[FRONTEND_DIST_KEY] = dist_path
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.router.add_static("/assets", assets_path)
        app.router.add_get("/", _spa_entry)
        app.router.add_get(r"/{tail:(?!api|health|assets).*$}", _spa_entry)
    app.on_startup.append(_start_sandbox_janitor)
    app.on_cleanup.append(_stop_sandbox_janitor)
    return app
