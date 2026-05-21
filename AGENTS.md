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

## 8. TDAI Memory Module Notes

Use this section as the current map for `backend/tdai_memory/` before changing memory behavior or integrating memory from other modules.

### Functional Layers

- L0 captures raw conversation messages through `capture.py`, writes them to PostgreSQL and daily JSONL files, and writes Qdrant vectors in the background when embedding is ready.
- L1 extracts structured memories from L0 conversations through the pipeline. Memory types are `persona`, `episodic`, and `instruction`.
- L2 groups L1 memories into scene blocks under `scene_blocks/` and maintains `scene_index.json`.
- L3 generates or updates profile files: `persona.md`, `SOUL.md`, and `IDENTITY.md`.
- Recall/Search loads stable profile context and searches L1/L0 records with keyword, embedding, or hybrid strategies.
- Offload summarizes tool results, stores offload references, builds MMD files, and supports context compression.

### Public Entry Points

- `backend/tdai_memory/__init__.py` is the package public API. It exports `MemoryManager`, `MemoryConfig`, `CompletedTurn`, `RecallResult`, `CaptureResult`, `MemorySearchParams`, `SearchResult`, and related models/config helpers.
- `backend/tdai_memory/manager.py::MemoryManager` is the facade other modules should call first.
- `MemoryManager` external methods are `initialize()`, `destroy()`, `recall()`, `capture()`, `search_memories()`, `search_conversations()`, `end_session()`, `set_identity_seed()`, `bootstrap_agent()`, and `seed()`.
- `get_postgres()`, `get_qdrant()`, `get_embedding()`, `get_scheduler()`, and `get_offload()` are low-level escape hatches. Use them only for necessary integration or diagnostics.

### Internal API Boundaries

- `capture.py`, `recall.py`, and `search.py` expose module-level functions, but they are currently intended to be wrapped by `MemoryManager`.
- `store/`, `pipeline/`, and `offload/` are internal collaboration layers. Other modules should not depend on their classes or functions unless there is a clear integration need.
- Current repo inspection found no direct Python imports of `tdai_memory` outside `backend/tdai_memory/`.

### Maintenance Notes

- New user-facing text or `logger` messages must follow this file's i18n/logger rules.
- Do not bypass `MemoryManager` to mutate PostgreSQL, Qdrant, or memory file layout unless the task explicitly requires lower-level repair.
- Known observation: `recall._rrf_fusion()` currently appears to return `fuseds`; treat that as a separate bugfix task if it needs to be fixed.
