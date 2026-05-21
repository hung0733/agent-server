import logging
import time
from typing import Any

from tdai_memory.models import CompletedTurn, ConversationMessage

logger = logging.getLogger(__name__)


async def seed_conversations(
    *,
    manager: Any,
    agent_id: str,
    sessions: list[dict],
    strict_round_role: bool = False,
    auto_fill_timestamps: bool = False,
) -> dict:
    imported = 0
    errors = 0
    l0_count = 0
    now_ms = int(time.time() * 1000)

    for session in sessions:
        session_key = session.get("session_key", "")
        session_id = session.get("session_id", session_key)
        rounds = session.get("rounds", [])
        session_started_at = session.get("started_at")

        for idx, round_data in enumerate(rounds):
            if strict_round_role:
                if not isinstance(round_data, dict):
                    errors += 1
                    logger.warning(
                        "Seed round %d in session '%s': not a dict, skipping",
                        idx, session_key,
                    )
                    continue
                has_user = "user" in round_data or "user_text" in round_data
                has_assistant = "assistant" in round_data or "assistant_text" in round_data
                if not (has_user and has_assistant):
                    errors += 1
                    logger.warning(
                        "Seed round %d in session '%s': strict_round_role requires "
                        "exactly one user + one assistant, skipping",
                        idx, session_key,
                    )
                    continue

            user_text = round_data.get("user") or round_data.get("user_text", "")
            assistant_text = round_data.get("assistant") or round_data.get("assistant_text", "")

            if auto_fill_timestamps:
                timestamp = now_ms - (len(rounds) - idx) * 100
            else:
                timestamp = round_data.get("timestamp", now_ms)

            messages = [
                ConversationMessage(role="user", content=user_text, timestamp=timestamp),
                ConversationMessage(role="assistant", content=assistant_text, timestamp=timestamp + 1),
            ]

            started_at = timestamp
            if session_started_at is not None:
                started_at = session_started_at
            elif "started_at" in round_data:
                started_at = round_data["started_at"]

            turn = CompletedTurn(
                user_text=user_text,
                assistant_text=assistant_text,
                messages=messages,
                session_key=session_key,
                session_id=session_id,
                started_at=started_at,
            )

            try:
                result = await manager.capture(agent_id=agent_id, turn=turn)
                imported += 1
                l0_count += result.l0_recorded_count
            except Exception:
                errors += 1
                logger.exception(
                    "Seed capture failed for session '%s' round %d",
                    session_key, idx,
                )

    return {"imported": imported, "errors": errors, "l0_count": l0_count}
