# pyright: reportMissingImports=false
"""
Agent / session management tool implementations.

Provides async functions that allow agents to interact with other agents
and collaboration sessions:
  - agents_list_impl      : List all sub-agents belonging to the same user
  - sessions_history_impl : Fetch message history for a collaboration session
  - sessions_send_impl    : Send a message to another agent via a session
  - sessions_spawn_impl   : Create a new collaboration session with a target agent
  - session_status_impl   : Show status card (usage, timing, model info)

All functions are raw async callables (not @tool decorated) that are
wrapped into StructuredTools by tools.py with agent_db_id injection.

Import path: tools.agent_tools
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.agent_message_dao import AgentMessageDAO
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dao.token_usage_dao import TokenUsageDAO
from db.dto.collaboration_dto import AgentMessageCreate, CollaborationSessionCreate
from db.types import MessageType
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


# ---------------------------------------------------------------------------
# sessions_history
# ---------------------------------------------------------------------------

async def sessions_history_impl(
    session_id: str,
    limit: int = 50,
    agent_db_id: str = "",
) -> str:
    """Fetch the message history of a collaboration session.

    Args:
        session_id: The ``session_id`` string of the collaboration session
            (e.g. ``session-<uuid>``).
        limit: Maximum number of messages to return (default 50).
        agent_db_id: Auto-injected calling agent instance UUID.

    Returns:
        Formatted message history, newest messages last.
    """
    if not agent_db_id:
        return _("❌ 無法獲取 agent_db_id，此工具只能在 agent 上下文中使用。")

    logger.info(_("[sessions_history] session_id=%s, caller=%s"), session_id, agent_db_id)
    try:
        collab = await CollaborationSessionDAO.get_by_session_id(session_id)
        if not collab:
            return _("❌ 找不到 session: %s") % session_id

        messages = await AgentMessageDAO.get_by_collaboration_id(
            collab.id, limit=limit
        )
        if not messages:
            return _("📭 此 session 沒有訊息記錄: %s") % session_id

        lines = [
            _("💬 Session 歷史記錄: %s (%d 條)") % (session_id, len(messages)),
            "",
        ]
        for msg in messages:
            sender = str(msg.sender_agent_id) if msg.sender_agent_id else _("系統")
            ts = msg.created_at.isoformat() if hasattr(msg, "created_at") else ""
            content_preview = str(msg.content_json)[:200]
            lines.append(f"[{ts}] {msg.message_type}  發送: {sender}")
            lines.append(f"  {content_preview}")
            lines.append("")

        return "\n".join(lines).rstrip()
    except Exception as exc:
        logger.error(_("[sessions_history] ❌ 查詢失敗: %s"), exc, exc_info=True)
        return _("❌ sessions_history 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# sessions_send
# ---------------------------------------------------------------------------

async def sessions_send_impl(
    session_id: str,
    content: str,
    receiver_agent_id: str = "",
    sender_agent_id: str = "",
    message_type: str = "request",
    agent_db_id: str = "",
) -> str:
    """Send a message to another agent via a collaboration session.

    Args:
        session_id: The ``session_id`` string of the collaboration session.
        content: Message content to send (stored as ``{"text": content}``).
        receiver_agent_id: UUID of the receiving agent instance (optional).
        sender_agent_id: UUID of the sending agent instance.  Defaults to the
            calling agent (``agent_db_id``) when not explicitly provided.
        message_type: Message type string — one of ``request``, ``response``,
            ``notification``, ``ack``, ``tool_call``, ``tool_result``.
            Defaults to ``request``.
        agent_db_id: Auto-injected calling agent instance UUID.

    Returns:
        Success message with the new message ID, or an error.
    """
    if not agent_db_id:
        return _("❌ 無法獲取 agent_db_id，此工具只能在 agent 上下文中使用。")

    # Resolve sender: explicit param takes precedence over injected agent_db_id
    effective_sender = sender_agent_id or agent_db_id

    logger.info(
        _("[sessions_send] session=%s sender=%s receiver=%s"),
        session_id, effective_sender, receiver_agent_id,
    )
    try:
        collab = await CollaborationSessionDAO.get_by_session_id(session_id)
        if not collab:
            return _("❌ 找不到 session: %s") % session_id

        try:
            msg_type = MessageType(message_type)
        except ValueError:
            return _("❌ 無效的 message_type: %s") % message_type

        create_dto = AgentMessageCreate(
            collaboration_id=collab.id,
            sender_agent_id=UUID(effective_sender) if effective_sender else None,
            receiver_agent_id=UUID(receiver_agent_id) if receiver_agent_id else None,
            message_type=msg_type,
            content_json={"text": content},
        )
        msg = await AgentMessageDAO.create(create_dto)
        return _(
            "✅ 訊息已發送\n"
            "訊息 ID   : %s\n"
            "Session   : %s\n"
            "發送者    : %s\n"
            "接收者    : %s\n"
            "類型      : %s"
        ) % (
            msg.id,
            session_id,
            effective_sender or _("(無)"),
            receiver_agent_id or _("(廣播)"),
            message_type,
        )
    except Exception as exc:
        logger.error(_("[sessions_send] ❌ 發送失敗: %s"), exc, exc_info=True)
        return _("❌ sessions_send 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# sessions_spawn
# ---------------------------------------------------------------------------

async def sessions_spawn_impl(
    to_agent_id: str,
    session_name: str = "",
    agent_db_id: str = "",
) -> str:
    """Create a new collaboration session with a target agent.

    The calling agent becomes the ``main_agent_id`` of the new session.

    Args:
        to_agent_id: UUID of the target agent instance to collaborate with.
        session_name: Optional human-readable session name.
        agent_db_id: Auto-injected calling agent instance UUID.

    Returns:
        Session details including the new ``session_id`` for subsequent
        ``sessions_send`` / ``sessions_history`` calls.
    """
    if not agent_db_id:
        return _("❌ 無法獲取 agent_db_id，此工具只能在 agent 上下文中使用。")

    logger.info(
        _("[sessions_spawn] caller=%s target=%s"), agent_db_id, to_agent_id
    )
    try:
        import uuid as _uuid

        caller = await AgentInstanceDAO.get_by_id(UUID(agent_db_id))
        if not caller:
            return _("❌ 找不到呼叫 Agent: %s") % agent_db_id

        target = await AgentInstanceDAO.get_by_id(UUID(to_agent_id))
        if not target:
            return _("❌ 找不到目標 Agent: %s") % to_agent_id

        new_session_id = f"session-{_uuid.uuid4()}"
        collab = await CollaborationSessionDAO.create(
            CollaborationSessionCreate(
                user_id=caller.user_id,
                main_agent_id=caller.id,
                session_id=new_session_id,
                name=session_name or f"{caller.name} ↔ {target.name}",
            )
        )
        return _(
            "✅ 協作 Session 已建立\n"
            "Session ID : %s\n"
            "DB ID      : %s\n"
            "主 Agent   : %s (%s)\n"
            "目標 Agent : %s (%s)"
        ) % (
            new_session_id,
            collab.id,
            caller.name,
            agent_db_id,
            target.name,
            to_agent_id,
        )
    except Exception as exc:
        logger.error(_("[sessions_spawn] ❌ 建立失敗: %s"), exc, exc_info=True)
        return _("❌ sessions_spawn 失敗: %s") % str(exc)


# ---------------------------------------------------------------------------
# session_status
# ---------------------------------------------------------------------------

async def session_status_impl(
    agent_db_id: str = "",
) -> str:
    """Show a status card for the calling agent: token usage, timing, and model info.

    Args:
        agent_db_id: Auto-injected calling agent instance UUID.

    Returns:
        Formatted status card.
    """
    if not agent_db_id:
        return _("❌ 無法獲取 agent_db_id，此工具只能在 agent 上下文中使用。")

    logger.info(_("[session_status] 查詢狀態: agent=%s"), agent_db_id)
    try:
        agent = await AgentInstanceDAO.get_by_id(UUID(agent_db_id))
        if not agent:
            return _("❌ 找不到 Agent 實例: %s") % agent_db_id

        # Token usage summary — filter user records by this agent_id
        try:
            all_usage = await TokenUsageDAO.get_by_user_id(agent.user_id, limit=50)
            agent_usage = [u for u in all_usage if str(u.agent_id) == agent_db_id]
            latest = agent_usage[0] if agent_usage else None
        except Exception:
            latest = None

        lines = [
            _("📊 Agent 狀態卡"),
            "=" * 40,
            _("名稱        : %s") % agent.name,
            _("ID          : %s") % agent.id,
            _("狀態        : %s") % agent.status,
            _("Sub-Agent   : %s") % (_("是") if agent.is_sub_agent else _("否")),
        ]

        if agent.last_heartbeat_at:
            lines.append(_("最後心跳    : %s") % agent.last_heartbeat_at.isoformat())

        if latest:
            lines.append("")
            lines.append(_("🔢 最近 Token 用量"))
            lines.append(_("  輸入  : %s") % getattr(latest, "input_tokens", "-"))
            lines.append(_("  輸出  : %s") % getattr(latest, "output_tokens", "-"))
            lines.append(_("  模型  : %s") % getattr(latest, "model_name", "-"))

        return "\n".join(lines)
    except Exception as exc:
        logger.error(_("[session_status] ❌ 查詢失敗: %s"), exc, exc_info=True)
        return _("❌ session_status 失敗: %s") % str(exc)
