# pyright: reportMissingImports=false
"""Agent management tool implementations.

Provides async functions that allow agents to discover sub-agents and submit
delegation tasks.

All functions are raw async callables (not @tool decorated) that are wrapped
into StructuredTools by tools.py with agent_db_id injection.

Import path: tools.agent_tools
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dao.task_dao import TaskDAO
from db.dao.task_queue_dao import TaskQueueDAO
from db.dto.collaboration_dto import CollaborationSessionCreate
from db.dto.task_dto import TaskCreate
from db.dto.task_queue_dto import TaskQueueCreate
from db.types import Priority, TaskStatus
from i18n import _

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# agents_list
# ---------------------------------------------------------------------------

async def agents_list_impl(
    agent_db_id: str = "",
) -> str:
    """List all sub-agents that belong to the same user as the calling agent.

    Args:
        agent_db_id: Auto-injected calling agent instance UUID.

    Returns:
        Formatted list of sub-agents (name, id, status, type).
    """
    if not agent_db_id:
        return _("❌ 無法獲取 agent_db_id，此工具只能在 agent 上下文中使用。")

    logger.info(_("[agents_list] 查詢 sub-agents, caller=%s"), agent_db_id)
    try:
        caller = await AgentInstanceDAO.get_by_id(UUID(agent_db_id))
        if not caller:
            return _("❌ 找不到 Agent 實例: %s") % agent_db_id

        all_agents = await AgentInstanceDAO.get_by_user_id(caller.user_id)
        sub_agents = [a for a in all_agents if a.is_sub_agent and str(a.id) != agent_db_id]

        if not sub_agents:
            return _("📭 此用戶沒有其他 sub-agents")

        lines = [_("🤖 Sub-Agents 列表 (共 %d 個)") % len(sub_agents), ""]
        for agent in sub_agents:
            lines.append(_("📌 %s") % agent.name)
            lines.append(_("   ID    : %s") % agent.id)
            lines.append(_("   狀態  : %s") % agent.status)
            lines.append(_("   類型ID: %s") % agent.agent_type_id)
            lines.append("")

        return "\n".join(lines).rstrip()
    except Exception as exc:
        logger.error(_("[agents_list] ❌ 查詢失敗: %s"), exc, exc_info=True)
        return _("❌ agents_list 失敗: %s") % str(exc)


async def submit_delegate_task_impl(
    goal: str,
    instruction: str,
    callback: dict[str, Any],
    agent_db_id: str = "",
) -> str:
    """Submit an asynchronous agent-to-agent delegation task.

    Args:
        goal: Final user goal appended later to the sender agent system prompt.
        instruction: The concrete work order sent from sender agent to sub-agent.
        callback: Callback channel payload for replying to the user later.
        agent_db_id: Auto-injected calling agent instance UUID.

    Returns:
        Acceptance message containing the created task ID.
    """
    if not agent_db_id:
        return _("❌ 無法獲取 agent_db_id，此工具只能在 agent 上下文中使用。")

    logger.info(_("[submit_delegate_task] caller=%s"), agent_db_id)
    try:
        caller = await AgentInstanceDAO.get_by_id(UUID(agent_db_id))
        if not caller:
            return _("❌ 找不到 Agent 實例: %s") % agent_db_id

        task = await TaskDAO.create(
            TaskCreate(
                user_id=caller.user_id,
                agent_id=caller.id,
                task_type="agent_to_agent",
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload={
                    "task_execution_type": "agent_to_agent",
                    "goal": goal,
                    "instruction": instruction,
                    "callback": callback,
                    "requester_agent_id": str(caller.id),
                    "acceptance_mode": "manager_llm_review",
                },
            )
        )
        await TaskQueueDAO.create(
            TaskQueueCreate(
                task_id=task.id,
                status=TaskStatus.pending,
                priority=10,
            )
        )

        return _(
            "✅ 已經落單，會安排 sub-agent 跟進。\n"
            "Task ID: %s\n"
            "完成後會按 callback 設定通知用戶。"
        ) % task.id
    except Exception as exc:
        logger.error(_("[submit_delegate_task] ❌ 建立任務失敗: %s"), exc, exc_info=True)
        return _("❌ submit_delegate_task 失敗: %s") % str(exc)
