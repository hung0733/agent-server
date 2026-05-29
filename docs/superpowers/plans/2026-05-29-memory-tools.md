# Memory Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two LangGraph-callable TDAI memory search tools in `backend/tools/memory.py`.

**Architecture:** Create a focused tools module that wraps `MemoryManager.instance().search_memories()` and `search_conversations()`. Use `ToolRuntime` to read `agent_id` and `thread_id` from LangGraph config, and keep graph binding unchanged per方案 A.

**Tech Stack:** Python, LangChain `@tool`, LangGraph `ToolRuntime`, Pydantic args schemas, pytest.

---

### Task 1: Memory Tool Tests

**Files:**
- Create: `tests/test_tools_memory.py`

- [ ] Write tests for schemas and runtime-config forwarding.
- [ ] Run `pytest tests/test_tools_memory.py -q` and verify it fails because `backend.tools.memory` does not exist.

### Task 2: Memory Tools Module

**Files:**
- Create: `backend/tools/memory.py`
- Modify: `backend/i18n.py`

- [ ] Add `tdai_memory_search`, `tdai_conversation_search`, and `MemoryTools`.
- [ ] Add i18n keys for tool descriptions, field descriptions, and log messages.
- [ ] Run `pytest tests/test_tools_memory.py -q` and verify it passes.

### Task 3: Focused Verification

**Files:**
- No new files.

- [ ] Run `pytest tests/test_tools_memory.py tests/test_tools_system.py tests/test_tools_sandbox.py -q`.
- [ ] Inspect `git diff` to ensure only the planned files changed.
