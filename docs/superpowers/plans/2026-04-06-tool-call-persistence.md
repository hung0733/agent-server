# Tool Call Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist actual DB-registered tool executions into the `tool_calls` table.

**Architecture:** Keep the change localized to the dynamic tool loader so the runtime executor becomes responsible for recording tool execution lifecycle events. Use a minimal metadata handoff from graph config to `get_tools()` so each invocation can link back to the current task when available.

**Tech Stack:** Python 3.12, asyncio, pytest, SQLAlchemy DAO layer, LangChain StructuredTool

---

### Task 1: Lock the executor persistence behavior with tests

**Files:**
- Create: `tests/unit/test_tools_tool_call_persistence.py`
- Reference: `src/tools/tools.py`
- Reference: `docs/superpowers/specs/2026-04-06-tool-call-persistence-design.md`

- [ ] **Step 1: Write the failing success-path test**

Add a test that builds an executor for `tests.unit.simple_tool_module:successful_tool`, injects `task_id`, `tool_id`, and `tool_version_id`, calls the executor, and asserts `ToolCallDAO.create()` and `ToolCallDAO.update()` receive the expected lifecycle payloads.

- [ ] **Step 2: Run the targeted unit test and observe failure**

Run:

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_tools_tool_call_persistence.py -v
```

Expected: the success-path assertion fails because the executor does not yet persist tool calls.

- [ ] **Step 3: Add failing tests for failure-path and skip-path behavior**

Add one test that expects `status="failed"` plus `error_message` on tool exceptions, and one test that verifies no DAO calls happen when `task_id` is missing.

- [ ] **Step 4: Re-run the targeted unit test file**

Run:

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_tools_tool_call_persistence.py -v
```

Expected: the new tests fail for the missing persistence behavior.

### Task 2: Persist tool executions in the loader executor

**Files:**
- Modify: `src/tools/tools.py`
- Modify: `src/graph/butler.py`
- Test: `tests/unit/test_tools_tool_call_persistence.py`

- [ ] **Step 1: Thread `task_id` from graph config into `get_tools()`**

Read `task_id` from `config["configurable"]["args"]` in the graph nodes and pass it into `get_tools(agent_db_id, task_id=...)`.

- [ ] **Step 2: Implement minimal executor persistence helpers**

In `src/tools/tools.py`, add the smallest helpers needed to:

```python
def _normalize_tool_output(result: Any) -> dict[str, Any]:
    ...

def _tool_task_id(merged_config: dict[str, Any]) -> str | None:
    ...
```

Then update `_make_executor(...)` so it creates a `tool_calls` row before execution, captures elapsed time with `time.monotonic()`, and updates the row on success or failure.

- [ ] **Step 3: Keep persistence non-blocking**

Wrap DAO persistence calls in `try/except` blocks that log warnings instead of failing the real tool execution when database recording itself breaks.

- [ ] **Step 4: Re-run the targeted unit test file**

Run:

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_tools_tool_call_persistence.py -v
```

Expected: all tests in that file pass.

## Self-Review

- **Spec coverage:** The plan covers the approved scope: persist only actual executions, store success/failure state, and skip writes when `task_id` is unavailable.
- **Placeholder scan:** No `TODO`, `TBD`, or undefined follow-up steps remain.
- **Type consistency:** The plan consistently uses `task_id`, `tool_id`, `tool_version_id`, `ToolCallDAO.create()`, and `ToolCallDAO.update()`.
