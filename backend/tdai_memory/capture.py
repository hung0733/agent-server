from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from backend.i18n import t
from backend.tdai_memory.offload.manager import OffloadManager
from .models import (
    CaptureResult,
    CompletedTurn,
    ConversationMessage,
    L0Record,
    ToolCallMessage,
)
from .store.embedding import EmbeddingService
from .store.postgres import PostgresStore
from .store.qdrant import QdrantStore
from .utils.sanitize import should_capture_l0, strip_code_blocks

logger = logging.getLogger(__name__)

_capture_locks: dict[str, asyncio.Lock] = {}
_capture_locks_lock = asyncio.Lock()


async def _get_capture_lock(session_key: str) -> asyncio.Lock:
    async with _capture_locks_lock:
        if session_key not in _capture_locks:
            _capture_locks[session_key] = asyncio.Lock()
    return _capture_locks[session_key]


_RE_MEMORIES_BLOCK = re.compile(
    r"<relevant-memories>.*?</relevant-memories>\s*", re.DOTALL
)


def _make_l0_id(session_key: str, timestamp: int, idx: int) -> str:
    hex_part = uuid.uuid4().hex[:4]
    return f"l0_{session_key}_{timestamp}_{idx}_{hex_part}"


async def _embed_l0_background(
    records: list[L0Record],
    embedding: EmbeddingService,
    qdrant: QdrantStore,
) -> None:
    for record in records:
        try:
            vec = await embedding.embed(record.message_text)
            await qdrant.upsert_l0(record, vec)
        except Exception:
            logger.exception(
                t("tdai_memory.capture.background_l0_embed_failed"), record.id
            )


def _strip_memories_block(text: str) -> str:
    return _RE_MEMORIES_BLOCK.sub("", text)


def _apply_filtering(turn: CompletedTurn) -> list[ConversationMessage]:
    messages = list(turn.messages)

    if turn.original_user_message_count is not None and turn.user_text:
        target_index = turn.original_user_message_count - 1
        if 0 <= target_index < len(messages):
            stripped = _strip_memories_block(turn.user_text)
            messages[target_index] = ConversationMessage(
                role=messages[target_index].role,
                content=stripped,
                timestamp=messages[target_index].timestamp,
            )

    for i, msg in enumerate(messages):
        content = _strip_memories_block(msg.content)
        content = re.sub(
            r"data:image\/[^;]+;base64,[A-Za-z0-9+/=]+", "[image]", content
        )
        if msg.role == "assistant":
            content = strip_code_blocks(content)
        messages[i] = ConversationMessage(
            role=msg.role,
            content=content,
            timestamp=msg.timestamp,
        )

    return messages


async def perform_auto_capture(
    turn: CompletedTurn,
    agent_id: str,
    postgres: PostgresStore,
    qdrant: QdrantStore | None,
    embedding: EmbeddingService | None,
    data_dir: str,
    on_scheduler_notify: Callable[[str, str], Awaitable[None]] | None = None,
    bg_tasks: set[asyncio.Task] | None = None,
    plugin_start_timestamp: int = 0,
    offload_manager: Optional[OffloadManager] = None,
) -> CaptureResult:
    t_start = time.monotonic()

    if postgres.is_degraded():
        logger.warning(t("tdai_memory.capture.postgres_degraded_skipping"))
        return CaptureResult()

    filtered_msgs = _apply_filtering(turn)
    filtered_msgs = [m for m in filtered_msgs if should_capture_l0(m.content)]

    async with await _get_capture_lock(turn.session_key):
        runner_state = await postgres.read_runner_state(agent_id, turn.session_key)
        cursor = 0
        if runner_state is not None:
            cursor = runner_state["last_captured_timestamp"]
            round_index = runner_state.get("round_index", 0) + 1
        else:
            round_index = 1

        if cursor == 0 and plugin_start_timestamp > 0:
            cursor = plugin_start_timestamp

        if cursor > 0:
            filtered_msgs = [m for m in filtered_msgs if m.timestamp > cursor]

        now_epoch_ms = int(time.time() * 1000)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conversations_dir = os.path.join(data_dir, agent_id, "conversations")
        jsonl_path = os.path.join(conversations_dir, f"{date_str}.jsonl")

        def _write_jsonl() -> None:
            os.makedirs(conversations_dir, exist_ok=True)
            with open(jsonl_path, "a", encoding="utf-8") as f:
                for msg in filtered_msgs:
                    f.write(json.dumps(_msg_to_dict(msg), ensure_ascii=False) + "\n")

        await asyncio.to_thread(_write_jsonl)

        records: list[L0Record] = []
        msgs: list[dict] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for idx, msg in enumerate(filtered_msgs):
            content = msg.content
            if msg.role == "assistant":
                content = strip_code_blocks(content)
            record = L0Record(
                id=_make_l0_id(turn.session_key, msg.timestamp, idx),
                agent_id=agent_id,
                session_key=turn.session_key,
                session_id=turn.session_id,
                role=msg.role,
                message_text=content,
                recorded_at=now_iso,
                timestamp=msg.timestamp,
            )
            records.append(record)
            msgs.append({"role": msg.role, "content": content})

        for record in records:
            try:
                await postgres.upsert_l0(record)
            except Exception:
                logger.exception(t("tdai_memory.capture.upsert_l0_failed"), record.id)

        if offload_manager is not None:
            for tc in turn.tool_call:
                try:
                    await offload_manager.record_tool_call(
                        agent_id=agent_id,
                        session_key=turn.session_key,
                        tool_call_id=tc.tool_call_id,
                        tool_name=tc.tool_name,
                        tool_input=tc.tool_input,
                    )

                    await offload_manager.record_tool_result(
                        agent_id=agent_id,
                        session_key=turn.session_key,
                        tool_call_id=tc.tool_call_id,
                        result_text=tc.tool_result,
                        round_index=round_index,
                        timestamp=tc.timestamp,
                        conversation_messages=msgs,
                    )
                except Exception:
                    logger.exception(
                        t("tdai_memory.capture.offload_tool_message_failed"),
                        tc.tool_call_id,
                    )

        if len(records) > 0:
            try:
                await postgres.write_runner_state(
                    agent_id,
                    turn.session_key,
                    now_epoch_ms,
                    round_index=round_index,
                )
            except Exception:
                logger.exception(
                    t("tdai_memory.capture.write_runner_state_failed"),
                    agent_id,
                    turn.session_key,
                )

    vectors_written = 0
    if qdrant is not None and embedding is not None and embedding.is_ready():
        embed_task = asyncio.create_task(
            _embed_l0_background(records, embedding, qdrant)
        )
        if bg_tasks is not None:
            bg_tasks.add(embed_task)
            embed_task.add_done_callback(bg_tasks.discard)

    if on_scheduler_notify is not None:
        try:
            await on_scheduler_notify(agent_id, turn.session_key)
        except Exception:
            logger.exception(
                t("tdai_memory.capture.scheduler_notify_failed"),
                agent_id,
                turn.session_key,
            )

    elapsed = (time.monotonic() - t_start) * 1000
    logger.debug(
        t("tdai_memory.capture.done"),
        agent_id,
        turn.session_key,
        len(records),
        elapsed,
    )
    return CaptureResult(
        scheduler_notified=on_scheduler_notify is not None,
        l0_recorded_count=len(records),
        l0_vectors_written=vectors_written,
        filtered_messages=filtered_msgs,
    )


def _msg_to_dict(msg: ConversationMessage) -> dict:
    return {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp}
