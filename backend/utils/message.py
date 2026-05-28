import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from backend.dao.agent_msg_hist import AgentMsgHistDAO
from backend.dto.agent_msg_hist import AgentMsgHistCreate
from backend.i18n import t
from backend.tdai_memory.models import ConversationMessage, ToolCallMessage
from backend.db.session import async_session_factory

logger = logging.getLogger(__name__)


class MsgUtil:
    @staticmethod
    async def save_agent_msg_hist(dtos: list[AgentMsgHistCreate]):
        async with async_session_factory() as session:
            dao: AgentMsgHistDAO = AgentMsgHistDAO(session)
            for dto in dtos:
                await dao.create(dto)
            await session.commit()

    @staticmethod
    async def save_msg_hist_rec(dtos: list[AgentMsgHistCreate]):
        await MsgUtil.save_agent_msg_hist(dtos)
        logger.info(t("utils.message.saved_count") % len(dtos))

    @staticmethod
    def _ts_to_dt(ts: int) -> datetime:
        return (
            datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            if ts
            else datetime.now(timezone.utc)
        )

    @staticmethod
    def _dt_to_ts(dt: datetime) -> int:
        return int(dt.timestamp() * 1000)

    @staticmethod
    def timelines_to_base_msg(timelines: list[dict] | None) -> list[BaseMessage]:
        messages: list[BaseMessage] = []

        if timelines:
            for msg in timelines:
                dt = MsgUtil._ts_to_dt(msg.get("timestamp", 0))
                if msg["type"] == "user":
                    messages.append(
                        HumanMessage(
                            content=msg["content"], additional_kwargs={"datetime": dt}
                        )
                    )
                elif msg["type"] == "assistant":
                    messages.append(
                        AIMessage(
                            content=msg["content"], additional_kwargs={"datetime": dt}
                        )
                    )
                elif msg["type"] == "tool":
                    messages.append(
                        AIMessage(
                            content=msg["content"], additional_kwargs={"datetime": dt}
                        )
                    )

        return messages

    @staticmethod
    def base_msg_to_msg_hist_rec(
        messages: list[BaseMessage],
        session_db_id: int,
        step_id: str,
        conversation_metadata: Dict[str, str],
    ) -> list[AgentMsgHistCreate]:
        dtos: list[AgentMsgHistCreate] = []

        for message in messages:
            msg_dt: datetime | None = message.additional_kwargs.get("datetime")

            if isinstance(message, HumanMessage):
                dtos.append(
                    AgentMsgHistCreate(
                        session_id=session_db_id,
                        step_id=step_id,
                        sender=conversation_metadata.get("sender_name", ""),
                        msg_type="user",
                        content=str(message.content) if message.content else None,
                        create_dt=msg_dt,
                    )
                )

            elif isinstance(message, AIMessage):
                reasoning_content = message.additional_kwargs.get("reasoning_content")
                if reasoning_content:
                    dtos.append(
                        AgentMsgHistCreate(
                            session_id=session_db_id,
                            step_id=step_id,
                            sender=conversation_metadata.get("recv_name", ""),
                            msg_type="reasoning",
                            content=str(reasoning_content),
                            create_dt=msg_dt,
                        )
                    )

                if message.content:
                    dtos.append(
                        AgentMsgHistCreate(
                            session_id=session_db_id,
                            step_id=step_id,
                            sender=conversation_metadata.get("recv_name", ""),
                            msg_type="assistant",
                            content=str(message.content),
                            create_dt=msg_dt,
                        )
                    )

                for tc in getattr(message, "tool_calls", []):
                    args = tc.get("args", {})
                    truncated_args = {
                        k: (
                            v[:100] + "..."
                            if isinstance(v, str) and len(v) > 100
                            else v
                        )
                        for k, v in args.items()
                    }
                    content = t("utils.message.tool_call_content") % (
                        tc.get("name"),
                        truncated_args,
                    )
                    dtos.append(
                        AgentMsgHistCreate(
                            session_id=session_db_id,
                            step_id=step_id,
                            sender=conversation_metadata.get("recv_name", ""),
                            msg_type="tool_call",
                            content=content,
                            meta_data=json.dumps(tc, ensure_ascii=False, default=str),
                            create_dt=msg_dt,
                        )
                    )

            elif isinstance(message, ToolMessage):
                dtos.append(
                    AgentMsgHistCreate(
                        session_id=session_db_id,
                        step_id=step_id,
                        sender="system",
                        msg_type="tool_result",
                        content=str(message.content) if message.content else None,
                        create_dt=msg_dt,
                    )
                )

        return dtos

    @staticmethod
    def base_msg_to_tdai_memory_rec(
        messages: list[BaseMessage], conversation_metadata: Dict[str, str]
    ) -> tuple[str, str, list[ConversationMessage], list[ToolCallMessage]]:

        user_msg: str = ""
        assistant_msg: str = ""
        cm: list[ConversationMessage] = []
        tcm: list[ToolCallMessage] = []

        for message in messages:
            ts: int = MsgUtil._dt_to_ts(message.additional_kwargs["datetime"])
            if isinstance(message, HumanMessage):
                user_msg = str(message.content)
                cm.append(
                    ConversationMessage(
                        role="user",
                        content=str(message.content),
                        timestamp=ts,
                        metadata=conversation_metadata,
                    )
                )
            elif isinstance(message, AIMessage):
                if message.content:
                    assistant_msg += str(message.content) + "\n\n"
                    cm.append(
                        ConversationMessage(
                            role="assistant",
                            content=str(message.content),
                            timestamp=ts,
                            metadata=conversation_metadata,
                        )
                    )

                if hasattr(message, "tool_calls") and len(message.tool_calls) > 0:
                    for tc in getattr(message, "tool_calls", []):
                        args = tc.get("args", {})
                        tool_call_id = str(tc.get("id") or "")
                        tool_name = str(tc.get("name") or "")
                        tcm.append(
                            ToolCallMessage(
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                tool_input=args,
                                tool_result="",
                                timestamp=ts,
                            )
                        )

            elif isinstance(message, ToolMessage) and message.content:
                for tc in tcm:
                    if tc.tool_call_id == message.tool_call_id:
                        tc.tool_result = str(message.content)

        return user_msg, assistant_msg, cm, tcm
