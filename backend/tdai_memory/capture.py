from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from backend.i18n import t
from backend.tdai_memory.models import CaptureResult, CompletedTurn, ConversationMessage, L0Record
from backend.tdai_memory.store.embedding import EmbeddingService
from backend.tdai_memory.store.postgres import PostgresStore
from backend.tdai_memory.store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_MEMORIES_BLOCK_RE = re.compile(r"<relevant-memories>.*?</relevant-memories>\s*", re.DOTALL)


def _strip_memories_block(text: str) -> str:
    return _MEMORIES_BLOCK_RE.sub("", text)


def _make_l0_id(session_key: str, timestamp: int, idx: int) -> str:
    return f"l0_{session_key}_{timestamp}_{idx}_{uuid.uuid4().hex[:4]}"


def _apply_filtering(
    turn: CompletedTurn,
) -> list[ConversationMessage]:
    filtered: list[ConversationMessage] = []

    if turn.original_user_message_count is not None:
        for msg in turn.messages:
            content = _strip_memories_block(msg.content)
            filtered.append(
                ConversationMessage(role=msg.role, content=content, timestamp=msg.timestamp)
            )
    else:
        filtered = list(turn.messages)

    return filtered


async def _embed_l0_background(
    records: list[L0Record],
    embedding: EmbeddingService,
    qdrant: QdrantStore,
) -> None:
    for record in records:
        try:
            vector = await embedding.embed(record.message_text)
            await qdrant.upsert_l0(record, vector)
        except Exception:
            logger.exception(t("tdai_memory.capture.l0_embed_upsert_failed"), record.id)


async def perform_auto_capture(
    turn: CompletedTurn,
    agent_id: str,
    postgres: PostgresStore,
    qdrant: QdrantStore,
    embedding: EmbeddingService,
    data_dir: str,
    on_scheduler_notify: Callable[[str, str], Awaitable[None]] | None = None,
) -> CaptureResult:
    filtered_msgs = _apply_filtering(turn)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conversations_dir = os.path.join(data_dir, agent_id, "conversations")
    jsonl_path = os.path.join(conversations_dir, f"{date_str}.jsonl")

    def _write_jsonl() -> None:
        os.makedirs(conversations_dir, exist_ok=True)
        with open(jsonl_path, "a") as f:
            for msg in filtered_msgs:
                f.write(msg.model_dump_json() + "\n")

    await asyncio.to_thread(_write_jsonl)

    records: list[L0Record] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for idx, msg in enumerate(filtered_msgs):
        record = L0Record(
            id=_make_l0_id(turn.session_key, msg.timestamp, idx),
            agent_id=agent_id,
            session_key=turn.session_key,
            session_id=turn.session_id,
            role=msg.role,
            message_text=msg.content,
            recorded_at=now_iso,
            timestamp=msg.timestamp,
        )
        records.append(record)

    for record in records:
        await postgres.upsert_l0(record)

    asyncio.create_task(_embed_l0_background(records, embedding, qdrant))

    if on_scheduler_notify is not None:
        await on_scheduler_notify(agent_id, turn.session_key)

    return CaptureResult(
        l0_recorded_count=len(filtered_msgs),
        l0_vectors_written=0,
        scheduler_notified=on_scheduler_notify is not None,
        filtered_messages=filtered_msgs,
    )
