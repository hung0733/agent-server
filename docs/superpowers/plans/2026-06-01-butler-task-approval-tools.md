# Butler Task Approval Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded `assign_task` approval for butler conversations and task listing/detail tools.

**Architecture:** Keep task persistence in `backend.tools.system` and `AssignedTaskDAO`. Add a small graph-level butler approval gate so `assign_task` calls become user approval prompts before DB writes, with WhatsApp interactive buttons where channel metadata is available.

**Tech Stack:** Python, LangGraph, LangChain tools, SQLAlchemy async ORM, pytest, project i18n.

---

### Task 1: Approval Gate Tests

**Files:**
- Modify: `tests/test_agent_runtime.py`
- Modify: `backend/graph/graph_node.py`
- Modify: `backend/graph/bulter.py`

- [ ] Add tests proving an `assign_task` tool call is intercepted before DB execution and returns an approval response.
- [ ] Add tests proving an approval button response executes the stored task and ends the turn.
- [ ] Implement minimal butler graph nodes/routes to satisfy those tests.

### Task 2: Task Query Tool Tests

**Files:**
- Modify: `tests/test_tools_system.py`
- Modify: `backend/dao/assigned_task.py`
- Modify: `backend/tools/system.py`
- Modify: `backend/i18n.py`

- [ ] Add tests for `list_assigned_tasks`: unfinished tasks plus completed/failed/cancelled tasks updated within 24 hours.
- [ ] Add tests for `read_assigned_task`: scoped by user and responsible agent, returns ordered steps.
- [ ] Implement DAO methods and two tools with i18n descriptions and errors.

### Task 3: WhatsApp Interactive Approval

**Files:**
- Modify: `backend/llm/types.py`
- Modify: `backend/channels/evolution_handler.py`
- Modify: `backend/channels/types.py`
- Modify: `backend/graph/bulter.py`

- [ ] Add a stream chunk payload type for interactive button sends, or reuse existing chunk metadata if available.
- [ ] Teach `WhatsAppMsgQueueTask.callback()` to send approval buttons through `send_interactive_buttons`.
- [ ] Keep text fallback when channel or phone number is unavailable.

### Task 4: Prompt and Verification

**Files:**
- Modify: `butler/IDENTITY.md`
- Modify: `backend/i18n.py`

- [ ] Update Task Handling Policy to describe approval button flow and end-of-turn behavior.
- [ ] Run targeted pytest for agent runtime and system tools.
- [ ] Run broader relevant tests if targeted tests pass.
