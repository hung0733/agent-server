"""Standalone prompt builder for new-agent bootstrap flows."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from db.crypto import CryptoManager
from db.dao.llm_endpoint_group_dao import LLMEndpointGroupDAO
from db.dao.llm_level_endpoint_dao import LLMLevelEndpointDAO
from db.dto.llm_endpoint_dto import LLMEndpointWithLevel
from models.llm import build_streaming_chat_openai


NEW_AGENT_BOOTSTRAP_REMINDER = """<system-reminder>
# Bootstrap Mode - System Reminder

CRITICAL: Bootstrap mode ACTIVE - you are onboarding a new custom agent.
You are NOT the final agent. You are NOT here to roleplay the finished persona.
Your job is to run a short onboarding conversation that extracts the agent's
identity, relationship to the user, communication style, autonomy level,
pushback preference, and failure philosophy.

STRICT RULES:
- Ask only 1-3 focused questions per round.
- Prefer behavioral questions over abstract adjectives.
- Convert vague preferences into explicit operating rules.
- Track the core fields internally throughout the conversation.
- Occasionally tell the user what is already clear and what is still missing.
- Do NOT generate the full SOUL.md too early.
- Reach a usable first draft within 5-8 rounds when possible.

SAVE RULE:
- If the user explicitly asks to save, switch to synthesis mode immediately.
- Do not stay in open-ended interviewing once the user has asked to save.

---

## Responsibility

Your current responsibility is to guide a natural, efficient onboarding
conversation that turns abstract preferences into explicit behavioral rules.

Collect enough information to define:
- agent identity
- relationship framing
- communication defaults
- autonomy boundaries
- honesty and pushback style
- failure philosophy

Ask clarifying questions whenever needed, but keep the conversation moving.
Do not make large assumptions while core information is still missing.
You should periodically summarize progress in simple language.

---

## Important

The user wants a usable first draft, not a polished personality essay.
You must not drift into generic persona writing, unstructured chatting, or
premature finalization. First extract. Then synthesize only when the user
explicitly asks to save.

This mode overrides generic assistant behavior for the NEW agent workflow.
</system-reminder>"""

NEW_AGENT_SYNTHESIS_REMINDER = """<system-reminder>
# Synthesis Mode - System Reminder

Your operational mode has changed from bootstrap to synthesis.
You are no longer collecting open-ended preferences.
You must now compress the onboarding conversation into a concise English
first draft of `SOUL.md`.

STRICT RULES:
- Under 300 words when possible.
- Every line must be grounded in user-stated or strongly implied preferences.
- Write traits as behavioral rules, not adjectives.
- Make the relationship framing explicit.
- Include communication defaults and language rules if known.
- Include an autonomy rule.
- Include a pushback / honesty rule.
- Include a failure rule that makes repeated mistakes unacceptable.
- Preserve room for future learning without making the agent generic.

ASSUMPTION RULE:
- You may make reasonable assumptions only for minor gaps.
- You must NOT invent missing core identity, relationship framing,
  communication style, autonomy level, pushback preference, or failure philosophy.
- If a core item is still incomplete, state the assumption plainly and keep it minimal.

NEXT STEP:
- After drafting `SOUL.md`, immediately switch to build mode.

---

## Responsibility

Your responsibility is to synthesize, not to continue interviewing.
Turn the collected signal into a compact, usable soul artifact that can be saved.

---

## Important

Do not write a generic system prompt.
Do not write a personality essay.
Write a concise, durable `SOUL.md` first draft in English.

This mode overrides generic assistant behavior for the save workflow.
</system-reminder>"""

NEW_AGENT_BUILD_REMINDER = """<system-reminder>
Your operational mode has changed from plan to build.
You are no longer in read-only mode.
You are permitted to make file changes, run shell commands, and utilize your arsenal of tools as needed.
</system-reminder>"""

NEW_AGENT_MODE_REMINDERS = {
    "bootstrap": NEW_AGENT_BOOTSTRAP_REMINDER,
    "synthesis": NEW_AGENT_SYNTHESIS_REMINDER,
    "build": NEW_AGENT_BUILD_REMINDER,
}


def strip_mode_reminders(prompt: str) -> str:
    cleaned = prompt
    for reminder in NEW_AGENT_MODE_REMINDERS.values():
        cleaned = cleaned.replace(reminder, "")
    return cleaned.strip()


def format_memory_blocks_prompt(memory_blocks: Iterable[object]) -> str:
    prompt_parts: list[str] = []
    for block in memory_blocks:
        memory_type = getattr(block, "memory_type", "")
        content = getattr(block, "content", "")
        if memory_type and content:
            prompt_parts.append(f"<{memory_type}>\n\n{content}\n\n</{memory_type}>")
    return "\n\n".join(prompt_parts).strip()


def build_mode_prompt(memory_blocks: Iterable[object], mode: str) -> str:
    base_prompt = strip_mode_reminders(format_memory_blocks_prompt(memory_blocks))
    reminder = NEW_AGENT_MODE_REMINDERS[mode]
    if base_prompt:
        return f"{base_prompt}\n\n{reminder}"
    return reminder


async def _resolve_active_endpoints(agent: Any, user_id: Any) -> list[LLMEndpointWithLevel]:
    endpoints = await LLMLevelEndpointDAO.get_by_agent_instance_id(agent.id)
    if endpoints:
        return [endpoint for endpoint in endpoints if endpoint.is_active]

    default_group = await LLMEndpointGroupDAO.get_default_group(user_id)
    if default_group is None:
        return []

    group_endpoints = await LLMLevelEndpointDAO.get_by_group_id(default_group.id)
    return [endpoint for endpoint in group_endpoints if endpoint.is_active]


def _pick_endpoint(endpoints: Sequence[LLMEndpointWithLevel]) -> LLMEndpointWithLevel | None:
    if not endpoints:
        return None
    sorted_endpoints = sorted(
        endpoints,
        key=lambda endpoint: (endpoint.difficulty_level, -endpoint.priority, endpoint.name),
    )
    return sorted_endpoints[0]


async def run_new_agent_bootstrap_turn(
    *,
    agent: Any,
    user_id: Any,
    mode: str,
    memory_blocks: Iterable[object],
    history: Sequence[dict[str, str]],
    message: str,
) -> str:
    endpoint = _pick_endpoint(await _resolve_active_endpoints(agent, user_id))
    if endpoint is None:
        raise ValueError("no_active_llm_endpoint")

    api_key = (
        CryptoManager().decrypt(endpoint.api_key_encrypted)
        if endpoint.api_key_encrypted
        else "EMPTY"
    )
    model = build_streaming_chat_openai(
        base_url=endpoint.base_url,
        api_key=SecretStr(api_key),
        model_name=endpoint.model_name,
    )

    transcript: list[Any] = [SystemMessage(content=build_mode_prompt(memory_blocks, mode))]
    for item in history:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            transcript.append(AIMessage(content=content))
        else:
            transcript.append(HumanMessage(content=content))
    if message.strip():
        transcript.append(HumanMessage(content=message.strip()))

    response = await model.ainvoke(transcript)
    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(str(part) for part in content).strip()
    return str(content).strip()
