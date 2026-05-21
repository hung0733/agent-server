# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. 所有對話使用香港中文作為溝通語言

## 2. i18n and Logger Text

All user-facing/display text and all `logger` log messages must support i18n.

- Read the active language from `.env` using `LANG_LOCALE`.
- The current default locale is `zh_HK`.
- Do not add hard-coded English or Chinese display text.
- Do not add hard-coded English or Chinese logger messages.
- Route display text and logger messages through the project i18n mechanism.
- Technical identifiers that are not meant for users, such as environment variable names, model names, database column names, or protocol constants, may remain untranslated.

## 3. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 4. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 5. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 6. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 7. Project Structure Notes

Use this section as the current project map before making structural changes.

### Runtime Flow

The main runtime path is:

```text
main.py
-> backend/channels/evolution_handler.py
-> backend/queues/message_queue.py
-> backend/queues/msg_queue_handle.py
-> backend/agent/agent.py
-> backend/graph/*
```

- `main.py` loads `.env`, configures logging, checks PostgreSQL, runs Alembic migrations, initializes the LangGraph checkpointer, starts the WhatsApp listener, and starts the message queue.
- `backend/channels/` handles Evolution WhatsApp inbound/outbound transport and converts provider payloads into internal message objects.
- `backend/services/whatsapp_session.py` resolves inbound WhatsApp messages into agent/session identity.
- `backend/queues/` serializes message handling and calls `Agent.send()`.
- `backend/agent/agent.py` loads runtime agent data, prepares system prompt content, initializes LLM models, and streams LangGraph output.
- `backend/graph/` owns the LangGraph workflow, graph nodes, graph store/checkpointer integration, and prompt modules.
- `backend/entities/`, `backend/dao/`, and `backend/dto/` are the SQLAlchemy entity, data access, and transfer layers.
- `backend/llm/` contains LLM model selection and runtime types.
- `backend/sandbox/` contains sandbox execution support.

### Legacy Memory Path

The original runtime memory tables have been deprecated and removed.

- `long_term_mem`, `short_term_mem`, and `memory_block` are no longer ORM metadata tables.
- `agent_msg_hist.is_summary` and `agent_msg_hist.is_analyst` have been removed.
- `Agent.prepare_sys_prompt()` currently sets an empty system prompt until the new memory module is wired into runtime recall.

### New `backend/tdai_memory/` Module

The `backend/tdai_memory/` package is a newer multi-layer memory module. Treat it as present but not fully wired into the main runtime unless you verify otherwise.

- `manager.py` is the facade: `initialize()`, `destroy()`, `recall()`, `capture()`, memory search, session end, and profile bootstrap.
- `config.py` reads memory-related `.env` values including PostgreSQL, Qdrant, embedding, TDAI LLM, and `MEMORY_DATA_DIR`.
- `models.py` defines L0 raw conversations, L1 structured memories, completed turns, recall/capture results, search params, and pipeline state.
- `capture.py` records completed turns to JSONL, PostgreSQL L0, and Qdrant L0 vectors.
- `recall.py` performs keyword/embedding/hybrid recall and builds memory context for prompts.
- `pipeline/` contains L1 extraction, L2 scene grouping, L3 profile generation, and the scheduler.
- `store/` contains PostgreSQL, Qdrant, and embedding service integrations.
- `offload/` contains context offload/compression support; it is disabled by default through config.

### Memory Storage

The current memory storage concept is the new TDAI memory schema:

- Alembic migration `20260521_0004_add_memory_schema_tables.py` creates `l0_conversations`, `l1_records`, `pipeline_state`, and `embedding_meta` under `MEMORY_SCHEMA`.
- Alembic migration `20260521_0005_drop_legacy_memory_schema.py` removes the legacy memory tables and old `agent_msg_hist` memory flags.

Qdrant is used by the new memory module for vector storage of L0 conversations and L1 memories.

### Current Integration Status

As of this note, `tdai_memory` is not fully connected to the normal agent message path.

- `main.py` does not initialize a `MemoryManager`.
- `handle_agent_message()` does not call `MemoryManager.recall()` before `Agent.send()`.
- `handle_agent_message()` does not call `MemoryManager.capture()` after the assistant response is complete.
- `Agent.proc_send()` does not inject recalled memory into the LangGraph state/config.
- The active system prompt is currently empty, not sourced from `tdai_memory` L1/L2/L3 data.

If asked to enable the new memory module, prefer a narrow integration:

```text
1. Initialize one MemoryManager during startup -> verify it is destroyed during shutdown.
2. Recall before the LLM turn -> verify recalled context reaches the prompt.
3. Capture after the final assistant response -> verify L0 rows and scheduler notification.
4. Add focused tests for disabled/failed recall, successful capture, and shutdown cleanup.
```

### Known Memory Module Risks To Check Before Wiring

Check these before relying on `tdai_memory` in production flow:

- `backend/tdai_memory/recall.py` has a likely typo: `_rrf_fusion()` returns `fuseds` instead of `fused`.
- `backend/tdai_memory/capture.py` returns `scheduled_notified`, but `CaptureResult` defines `scheduler_notified`.
- Several `tdai_memory` logger messages are hard-coded strings; project rules require logger text to go through i18n.
- Background L0 embedding tasks created by `capture.py` are not tracked by `MemoryManager._bg_tasks`, so shutdown cleanup may miss them.
- Qdrant collection names are hard-coded in `store/qdrant.py`, while `.env.example` defines Qdrant collection variables.
