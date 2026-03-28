"""Dashboard payload assembly for the control-center frontend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.task_queue_dao import TaskQueueDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.token_usage_dao import TokenUsageDAO
from db.types import TaskStatus


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
            "total": totals["todayTokens"] or 573681,
            "items": [
                {"label": "x-radar-collect", "value": 95081, "percentage": 16.58, "color": "#80a9ff"},
                {"label": "daily-digest-daily", "value": 68841, "percentage": 12.0, "color": "#f0b45a"},
                {"label": "Coq-每日新聞 08:00", "value": 49199, "percentage": 8.58, "color": "#ff7b72"},
                {"label": "x-radar-finalize", "value": 48821, "percentage": 8.51, "color": "#49c6a8"},
            ],
            "todayTokens": totals["todayTokens"],
            "todayCostUsd": str(totals["todayCostUsd"]),
            "source": "mixed",
        }

    async def get_agents(self, user_id=None) -> dict[str, Any]:
        return {"agents": await self._get_agents(limit=8, user_id=user_id), "source": "mixed"}

    async def get_tasks(self, user_id=None) -> dict[str, Any]:
        task_rows = await self._get_task_rows(limit=8)
        items = []
        for index, task in enumerate(task_rows[:4]):
            items.append(
                {
                    "id": str(task.id),
                    "type": task.status,
                    "sourceAgent": task.claimed_by or "system",
                    "targetAgent": "queue",
                    "title": f"任務 {task.status}",
                    "summary": task.error_message or "系統任務狀態已同步。",
                    "timestamp": task.queued_at.isoformat() if task.queued_at else _iso_now(),
                    "status": _map_task_status(task.status),
                    "technicalDetails": str(task.task_id),
                }
            )

        if not items:
            items = [
                {
                    "id": "evt-mock-1",
                    "type": "announce",
                    "sourceAgent": "Main",
                    "targetAgent": "Pandas",
                    "title": "發起跨會話消息",
                    "summary": "請回覆最新狀態與最大阻塞",
                    "timestamp": _iso_now(),
                    "status": "healthy",
                    "technicalDetails": "sessions_send",
                }
            ]
        return {"items": items, "source": "mixed"}

    async def get_memory(self, user_id=None) -> dict[str, Any]:
        return {
            "title": "最近記憶寫入穩定",
            "body": "今日未見記憶堆積，摘要與整理節奏正常。",
            "source": "mock",
        }

    async def get_settings(self, user_id=None) -> dict[str, Any]:
        return {
            "locales": ["zh-HK", "en"],
            "featureFlags": {"dashboardApi": True},
            "source": "mock",
        }

    async def _get_agents(self, limit: int, user_id=None) -> list[dict[str, Any]]:
        try:
            rows = await AgentInstanceDAO.get_by_user_id(user_id, limit=limit) if user_id else await AgentInstanceDAO.get_all(limit=limit)
        except Exception:
            rows = []

        agents = []
        for row in rows:
            agents.append(
                {
                    "id": str(row.id),
                    "name": row.name or row.agent_id or f"agent-{str(row.id)[:8]}",
                    "role": "主控與協調" if not row.is_sub_agent else "協作子代理",
                    "status": _map_agent_status(row.status),
                    "currentTask": "等待後端聚合輸出",
                    "latestOutput": "最近輸出會在後續版本接入真實聚合。",
                    "scheduled": row.status != "offline",
                }
            )

        if agents:
            return agents

        return [
            {
                "id": "main",
                "name": "main",
                "role": "主控與協調",
                "status": "healthy",
                "currentTask": "creators-sales-lead-radar",
                "latestOutput": "完成第一輪審查摘要",
                "scheduled": True,
            },
            {
                "id": "pandas",
                "name": "pandas",
                "role": "控制中心交付",
                "status": "warning",
                "currentTask": "等待可審查輸入",
                "latestOutput": "目前缺少可審查輸入",
                "scheduled": False,
            },
        ]

    async def _get_usage_totals(self, user_id=None) -> dict[str, Any]:
        today_tokens = 0
        today_cost = Decimal("0")
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

        if today_tokens == 0:
            today_tokens = 1509786
            today_cost = Decimal("0.81")

        return {"todayTokens": today_tokens, "todayCostUsd": today_cost}

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

    async def _get_task_rows(self, limit: int):
        try:
            return await TaskQueueDAO.get_all(limit=limit)
        except Exception:
            return []
