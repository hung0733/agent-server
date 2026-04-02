"""Dashboard payload assembly for the control-center frontend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.agent_tool_dao import AgentInstanceToolDAO
from db.dao.agent_message_dao import AgentMessageDAO
from db.dao.api_key_dao import APIKeyDAO
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from db.dao.llm_endpoint_group_dao import LLMEndpointGroupDAO
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dao.tool_dao import ToolDAO
from db.dao.task_queue_dao import TaskQueueDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.token_usage_dao import TokenUsageDAO
from db.types import TaskStatus
from utils.timezone import to_server_tz


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _format_currency(amount: Decimal) -> str:
    return f"${amount.quantize(Decimal('0.01'))}"


def _map_agent_status(status: str) -> str:
    return {
        "busy": "healthy",
        "idle": "idle",
        "error": "danger",
        "offline": "warning",
    }.get(status, "warning")


def _map_task_status(status: str) -> str:
    return {
        "completed": "healthy",
        "running": "healthy",
        "pending": "warning",
        "failed": "danger",
        "cancelled": "warning",
    }.get(status, "warning")


def _truncate_text(value: str, limit: int = 120) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _extract_message_content(content: Any) -> str:
    """Extract full message content without truncation."""
    if isinstance(content, str):
        return " ".join(content.split())

    if isinstance(content, dict):
        for key in ("summary", "content", "message", "text"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())

        for value in content.values():
            extracted = _extract_message_content(value)
            if extracted:
                return extracted

    if isinstance(content, list):
        for item in content:
            extracted = _extract_message_content(item)
            if extracted:
                return extracted

    return ""


def _summarize_message_content(content: Any) -> str:
    if isinstance(content, str):
        return _truncate_text(content)

    if isinstance(content, dict):
        for key in ("summary", "content", "message", "text"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return _truncate_text(value)

        for value in content.values():
            summary = _summarize_message_content(value)
            if summary:
                return summary

    if isinstance(content, list):
        for value in content:
            summary = _summarize_message_content(value)
            if summary:
                return summary

    return ""


def _agent_display_name(agent: Any) -> str:
    return agent.name or agent.agent_id or f"agent-{str(agent.id)[:8]}"


def _determine_agent_display(
    session_id: str,
    message_type: str,
    sender_agent_id: Any,
    receiver_agent_id: Any,
    agent_lookup: dict[Any, str],
) -> tuple[str, str]:
    """Determine sourceAgent and targetAgent display names based on session_id and message_type.

    Rules:
    - session-*/default-* + request: User Name -> Receiver Agent Name
    - session-*/default-* + response: Agent Name -> Receiver User Name
    - ghost-* + request: System -> Receiver Agent Name
    - ghost-* + response: Receiver Agent Name -> System
    - sender_agent_id not null + request: Sender Agent Name -> Receiver Agent Name
    - sender_agent_id not null + response: Receiver Agent Name -> Sender Agent Name

    Args:
        session_id: The collaboration session_id string.
        message_type: The message type (request/response).
        sender_agent_id: The sender agent ID (may be None).
        receiver_agent_id: The receiver agent ID (may be None).
        agent_lookup: Mapping from agent ID to agent display name.

    Returns:
        Tuple of (sourceAgent, targetAgent) display names.
    """
    is_request = message_type == "request"

    # Check session_id prefix
    if session_id.startswith("session-") or session_id.startswith("default-"):
        if is_request:
            # User -> Receiver Agent
            receiver_name = agent_lookup.get(receiver_agent_id, "system")
            return ("User", receiver_name)
        else:
            # Agent -> User
            sender_name = agent_lookup.get(sender_agent_id, "system")
            return (sender_name, "User")

    elif session_id.startswith("ghost-"):
        if is_request:
            # System -> Receiver Agent
            receiver_name = agent_lookup.get(receiver_agent_id, "system")
            return ("System", receiver_name)
        else:
            # Receiver Agent -> System
            receiver_name = agent_lookup.get(receiver_agent_id, "system")
            return (receiver_name, "System")

    # Agent-to-agent communication (sender_agent_id is not null)
    if sender_agent_id is not None:
        sender_name = agent_lookup.get(sender_agent_id, "system")
        receiver_name = agent_lookup.get(receiver_agent_id, "system")
        if is_request:
            # Sender Agent -> Receiver Agent
            return (sender_name, receiver_name)
        else:
            # Receiver Agent -> Sender Agent
            return (receiver_name, sender_name)

    # Fallback to original logic
    sender_name = agent_lookup.get(sender_agent_id, "system")
    receiver_name = agent_lookup.get(receiver_agent_id, "queue")
    return (sender_name, receiver_name)


@dataclass(slots=True)
class DashboardDataProvider:
    """Build dashboard responses from mixed real and assembled data."""

    queue: Any
    dedup: Any

    async def get_overview(self, user_id=None) -> dict[str, Any]:
        queue_pending = await self._get_pending_queue_count()
        active_schedule_count = await self._get_active_schedule_count()
        agents = await self._get_agents(limit=3, user_id=user_id)
        usage = await self._get_usage_totals(user_id=user_id)

        anomalies = 0
        stalled = 0
        budget_risk = 0
        pending_review = queue_pending
        score = max(70, 100 - pending_review * 4)

        if pending_review > 0:
            conclusion = f"系統整體穩定，但目前有 {pending_review} 項待人工確認。"
            headline = "需要跟進"
            status = "warning"
        else:
            conclusion = "系統整體穩定，今日未見需要立即升級處理的事件。"
            headline = "推進順暢"
            status = "healthy"

        active_agent_names = ", ".join(agent["name"] for agent in agents) if agents else "-"

        return {
            "summary": {
                "score": score,
                "headline": headline,
                "conclusion": conclusion,
                "status": status,
                "requiresIntervention": pending_review > 0,
            },
            "stats": [
                {
                    "label": "待審批",
                    "value": pending_review,
                    "note": f"{pending_review} 項待人工確認" if pending_review else "目前無需介入",
                    "status": "warning" if pending_review else "healthy",
                },
                {
                    "label": "運行異常",
                    "value": anomalies,
                    "note": "目前未見異常事件",
                    "status": "healthy",
                },
                {
                    "label": "停滯任務",
                    "value": stalled,
                    "note": "目前無需介入",
                    "status": "healthy",
                },
                {
                    "label": "預算風險",
                    "value": budget_risk,
                    "note": "今日預算安全",
                    "status": "healthy",
                },
            ],
            "activeAgents": agents,
            "shellMeta": {"lastUpdatedAt": _iso_now()},
            "railSummary": {
                "usageText": f"{usage['todayTokens']:,} tokens / {_format_currency(usage['todayCostUsd'])}",
                "activeAgentNames": active_agent_names,
                "scheduleCount": active_schedule_count,
            },
            "intervention": {
                "title": "兩項審批等待確認" if pending_review else "目前無需人工介入",
                "body": (
                    "Main 正整理可交付摘要，Pandas 正等待可審查輸入。"
                    if pending_review
                    else "系統節奏平穩，當前可維持既有處理節奏。"
                ),
                "source": "mixed",
            },
            "source": "mixed",
        }

    async def get_usage(self, user_id=None) -> dict[str, Any]:
        totals = await self._get_usage_totals(user_id=user_id)
        return {
            "total": totals["todayTokens"],
            "items": totals["items"],
            "todayTokens": totals["todayTokens"],
            "todayCostUsd": str(totals["todayCostUsd"]),
            "source": "mixed",
        }

    async def get_agents(self, user_id=None) -> dict[str, Any]:
        return {"agents": await self._get_agents(limit=8, user_id=user_id), "source": "mixed"}

    async def get_tasks(self, user_id=None) -> dict[str, Any]:
        agent_lookup = await self._get_agent_name_lookup(user_id=user_id)
        agent_ids = set(agent_lookup)
        task_rows = await self._get_user_scoped_task_rows(agent_ids=agent_ids, limit=8)
        message_rows = await self._get_user_scoped_message_rows(agent_ids=agent_ids, limit=8)
        items = []

        for task in task_rows:
            context = task.result_json if isinstance(task.result_json, dict) else {}
            # Convert timestamp to server timezone
            timestamp = to_server_tz(task.queued_at).isoformat() if task.queued_at else _iso_now()

            items.append(
                {
                    "id": str(task.id),
                    "type": task.status,
                    "sourceAgent": agent_lookup.get(task.claimed_by, "system"),
                    "targetAgent": "queue",
                    "title": f"任務 {task.status}",
                    "summary": task.error_message or "系統任務狀態已同步。",
                    "timestamp": timestamp,
                    "status": _map_task_status(task.status),
                    "group": context.get("group"),
                    "origin": context.get("origin"),
                    "relatedTaskId": context.get("relatedTaskId"),
                    "messageSnippet": None,
                }
            )

        for message, session_id in message_rows:
            # Get full content without truncation for frontend display
            full_content = _extract_message_content(message.content_json) or "最近消息已記錄。"

            # Determine sourceAgent and targetAgent based on session_id and message_type
            source_agent, target_agent = _determine_agent_display(
                session_id=session_id,
                message_type=getattr(message, "message_type", "request"),
                sender_agent_id=message.sender_agent_id,
                receiver_agent_id=message.receiver_agent_id,
                agent_lookup=agent_lookup,
            )

            # Convert timestamp to server timezone
            timestamp = to_server_tz(message.created_at).isoformat() if message.created_at else _iso_now()

            items.append(
                {
                    "id": str(message.id),
                    "type": "message",
                    "sourceAgent": source_agent,
                    "targetAgent": target_agent,
                    "title": "代理消息",
                    "summary": full_content,
                    "timestamp": timestamp,
                    "status": "healthy",
                    "group": None,
                    "origin": "message",
                    "relatedTaskId": None,
                    "messageSnippet": full_content,
                }
            )

        items.sort(key=lambda item: item["timestamp"], reverse=True)
        if not items:
            return {"items": [], "source": "mixed"}

        return {"items": items[:8], "source": "mixed"}

    async def get_memory(self, user_id=None) -> dict[str, Any]:
        agent_lookup = await self._get_agent_name_lookup(user_id=user_id)
        agent_ids = set(agent_lookup)
        task_rows = await self._get_user_scoped_task_rows(agent_ids=agent_ids, limit=8)
        message_rows = await self._get_user_scoped_message_rows(agent_ids=agent_ids, limit=8)

        recent_entries = []
        for task in task_rows:
            # Convert timestamp to server timezone
            timestamp = to_server_tz(task.queued_at).isoformat() if task.queued_at else _iso_now()
            recent_entries.append(
                {
                    "kind": "task",
                    "timestamp": timestamp,
                    "agent": agent_lookup.get(task.claimed_by, "system"),
                    "summary": task.error_message or f"任務 {task.status}",
                    "status": _map_task_status(task.status),
                }
            )

        for message, session_id in message_rows:
            # Convert timestamp to server timezone
            timestamp = to_server_tz(message.created_at).isoformat() if message.created_at else _iso_now()

            # Determine agent display name based on session_id and message_type
            source_agent, _ = _determine_agent_display(
                session_id=session_id,
                message_type=getattr(message, "message_type", "request"),
                sender_agent_id=message.sender_agent_id,
                receiver_agent_id=message.receiver_agent_id,
                agent_lookup=agent_lookup,
            )

            recent_entries.append(
                {
                    "kind": "message",
                    "timestamp": timestamp,
                    "agent": source_agent,
                    "summary": _summarize_message_content(message.content_json) or "最近消息已記錄。",
                    "status": "healthy",
                }
            )

        recent_entries.sort(key=lambda entry: entry["timestamp"], reverse=True)
        activity_count = len(task_rows) + len(message_rows)

        return {
            "stats": {
                "agents": len(agent_lookup),
                "tasks": len(task_rows),
                "messages": len(message_rows),
            },
            "health": {
                "status": "healthy" if activity_count else "idle",
                "summary": f"最近 {activity_count} 項用戶活動可歸因。",
            },
            "recentEntries": recent_entries[:5],
            "source": "mixed",
        }

    async def get_settings(self, user_id=None) -> dict[str, Any]:
        endpoints = []
        groups = []

        try:
            endpoint_rows = await LLMEndpointDAO.get_by_user_id(user_id)
        except Exception:
            endpoint_rows = []

        try:
            group_rows = await LLMEndpointGroupDAO.get_by_user_id(user_id)
        except Exception:
            group_rows = []
        try:
            api_key_rows = await APIKeyDAO.get_by_user_id(user_id)
        except Exception:
            api_key_rows = []

        for row in endpoint_rows:
            endpoints.append(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "baseUrl": row.base_url,
                    "modelName": row.model_name,
                    "isActive": row.is_active,
                    "apiKeyConfigured": bool(row.api_key_encrypted),
                }
            )

        for group in group_rows:
            try:
                level_rows = await LLMLevelEndpointDAO.get_by_group_id(group.id)
            except Exception:
                level_rows = []

            groups.append(
                {
                    "id": str(group.id),
                    "name": group.name,
                    "slots": [
                        {
                            "id": str(level.id),
                            "difficultyLevel": level.difficulty_level,
                            "involvesSecrets": level.involves_secrets,
                            "endpointId": str(level.endpoint_id),
                            "priority": level.priority,
                            "isActive": level.is_active,
                        }
                        for level in sorted(
                            level_rows,
                            key=lambda item: (item.difficulty_level, item.involves_secrets),
                        )
                    ],
                }
            )

        auth_keys = []
        for row in api_key_rows:
            auth_keys.append(
                {
                    "id": str(row.id),
                    "name": row.name or "未命名 Key",
                    "isActive": row.is_active,
                    "lastUsedAt": row.last_used_at.isoformat() if row.last_used_at else None,
                    "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
                    "createdAt": row.created_at.isoformat(),
                }
            )

        return {
            "locales": ["zh-HK", "en"],
            "featureFlags": {"dashboardApi": True},
            "endpoints": endpoints,
            "groups": groups,
            "authKeys": auth_keys,
            "source": "mixed",
        }

    async def get_agent_tools(self, user_id=None) -> dict[str, Any]:
        agent_rows = await self._get_user_agents(user_id=user_id, limit=100)
        type_name_lookup = await self._get_agent_type_name_lookup()
        try:
            tool_rows = await ToolDAO.get_active()
        except Exception:
            tool_rows = []

        available_tools = [
            {
                "id": str(tool.id),
                "name": tool.name,
                "description": tool.description,
                "isActive": tool.is_active,
            }
            for tool in tool_rows
        ]

        agents = []
        for row in agent_rows:
            try:
                effective_tool_ids = set(await AgentInstanceToolDAO.get_effective_tools(row.id))
            except Exception:
                effective_tool_ids = set()

            try:
                overrides = await AgentInstanceToolDAO.get_overrides_for_instance(row.id)
            except Exception:
                overrides = []

            override_map = {override.tool_id: override for override in overrides}
            tools = []
            for tool in tool_rows:
                override = override_map.get(tool.id)
                is_enabled = tool.id in effective_tool_ids
                if override is not None:
                    source = "override"
                elif is_enabled:
                    source = "type"
                else:
                    source = "inactive"

                tools.append(
                    {
                        "id": str(tool.id),
                        "name": tool.name,
                        "description": tool.description,
                        "isActive": tool.is_active,
                        "isEnabled": is_enabled,
                        "source": source,
                    }
                )

            type_id = str(row.agent_type_id) if row.agent_type_id else None
            agents.append(
                {
                    "id": str(row.id),
                    "name": _agent_display_name(row),
                    "role": type_name_lookup.get(type_id, "未知類型"),
                    "status": _map_agent_status(row.status),
                    "tools": tools,
                }
            )

        return {
            "agents": agents,
            "availableTools": available_tools,
            "source": "mixed",
        }

    async def _get_agents(self, limit: int, user_id=None) -> list[dict[str, Any]]:
        rows = await self._get_user_agents(user_id=user_id, limit=limit)
        type_name_lookup = await self._get_agent_type_name_lookup()
        agents = []
        for row in rows:
            type_id = str(row.agent_type_id) if row.agent_type_id else None
            agents.append(
                {
                    "id": str(row.id),
                    "name": _agent_display_name(row),
                    "role": type_name_lookup.get(type_id, "未知類型"),
                    "status": _map_agent_status(row.status),
                    "currentTask": "等待後端聚合輸出",
                    "latestOutput": "最近輸出會在後續版本接入真實聚合。",
                    "scheduled": row.status != "offline",
                    "isActive": row.is_active,
                    "isSubAgent": row.is_sub_agent,
                    "phoneNo": row.phone_no,
                    "whatsappKey": row.whatsapp_key,
                    "agentTypeId": type_id,
                    "agentTypeName": type_name_lookup.get(type_id),
                    "endpointGroupId": str(row.endpoint_group_id) if row.endpoint_group_id else None,
                }
            )

        return agents

    async def _get_agent_type_name_lookup(self) -> dict[str, str]:
        try:
            types = await AgentTypeDAO.get_all(limit=200)
            return {str(t.id): t.name for t in types}
        except Exception:
            return {}

    async def _get_user_agents(self, user_id=None, limit: int = 100):
        try:
            rows = await AgentInstanceDAO.get_by_user_id(user_id, limit=limit) if user_id else await AgentInstanceDAO.get_all(limit=limit)
        except Exception:
            rows = []

        return rows

    async def _get_agent_name_lookup(self, user_id=None) -> dict[Any, str]:
        try:
            rows = await AgentInstanceDAO.get_by_user_id(user_id, limit=100) if user_id else await AgentInstanceDAO.get_all(limit=100)
        except Exception:
            rows = []

        return {
            row.id: _agent_display_name(row)
            for row in rows
        }

    async def _get_user_scoped_task_rows(self, agent_ids: set[Any], limit: int) -> list[Any]:
        if not agent_ids:
            return []

        rows = []
        offset = 0
        batch_size = max(limit, 8)
        while len(rows) < limit:
            batch = await self._get_task_rows(limit=batch_size, offset=offset)
            if not batch:
                break

            rows.extend(task for task in batch if task.claimed_by in agent_ids)
            offset += len(batch)
            if len(batch) < batch_size:
                break

        return rows[:limit]

    async def _get_user_scoped_message_rows(self, agent_ids: set[Any], limit: int) -> list[tuple[Any, str]]:
        """Get user-scoped message rows with session_id.

        Args:
            agent_ids: Set of agent IDs to filter by.
            limit: Maximum number of rows to return.

        Returns:
            List of tuples: (message, session_id).
        """
        if not agent_ids:
            return []

        rows = []
        offset = 0
        batch_size = max(limit, 8)
        while len(rows) < limit:
            batch = await self._get_message_rows(limit=batch_size, offset=offset)
            if not batch:
                break

            rows.extend(
                (message, session_id)
                for message, session_id in batch
                if message.sender_agent_id in agent_ids or message.receiver_agent_id in agent_ids
            )
            offset += len(batch)
            if len(batch) < batch_size:
                break

        return rows[:limit]

    async def _get_usage_totals(self, user_id=None) -> dict[str, Any]:
        palette = ["#80a9ff", "#f0b45a", "#ff7b72", "#49c6a8", "#9f86ff", "#7cc6a0"]
        today_tokens = 0
        today_cost = Decimal("0")
        per_model: dict[str, int] = {}
        try:
            records = await TokenUsageDAO.get_by_user_id(user_id, limit=500) if user_id else await TokenUsageDAO.get_all(limit=500)
        except Exception:
            records = []

        today = datetime.now(UTC).date()
        for record in records:
            created_at = record.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if created_at.astimezone(UTC).date() == today:
                today_tokens += record.total_tokens
                today_cost += record.estimated_cost_usd
                label = record.model_name or "unknown"
                per_model[label] = per_model.get(label, 0) + record.total_tokens

        items = []
        if today_tokens > 0:
            for index, (label, value) in enumerate(
                sorted(per_model.items(), key=lambda item: item[1], reverse=True)
            ):
                items.append(
                    {
                        "label": label,
                        "value": value,
                        "percentage": round((value / today_tokens) * 100, 2),
                        "color": palette[index % len(palette)],
                    }
                )

        return {"todayTokens": today_tokens, "todayCostUsd": today_cost, "items": items}

    async def _get_pending_queue_count(self) -> int:
        try:
            if hasattr(self.queue, "get_stats"):
                stats = await self.queue.get_stats()
                return int(getattr(stats, "pending_tasks", 0))
            if hasattr(self.queue, "qsize"):
                return int(self.queue.qsize())
        except Exception:
            pass

        try:
            return len(await TaskQueueDAO.get_all(limit=50, status=TaskStatus.pending))
        except Exception:
            return 0

    async def _get_active_schedule_count(self) -> int:
        try:
            return len(await TaskScheduleDAO.get_active_schedules())
        except Exception:
            return 0

    async def _get_task_rows(self, limit: int, offset: int = 0):
        try:
            return await TaskQueueDAO.get_all(limit=limit, offset=offset)
        except Exception:
            return []

    async def _get_message_rows(self, limit: int, offset: int = 0):
        try:
            return await AgentMessageDAO.get_all_with_session_id(limit=limit, offset=offset)
        except Exception:
            return []
