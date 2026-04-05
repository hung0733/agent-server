# Orphan Schedule Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove existing orphan scheduled-task rows and prevent invalid schedules from retrying forever.

**Architecture:** Keep the fix localized to scheduler invalid-data handling and one targeted cleanup pass for known orphan template tasks. Treat missing agent linkage as a terminal data-integrity problem by deactivating the schedule instead of backing off.

**Tech Stack:** Python 3.12, asyncio, pytest, SQLAlchemy DAO layer

---

### Task 1: Update scheduler invalid-schedule behavior

**Files:**
- Modify: `src/scheduler/task_scheduler.py`
- Modify: `tests/unit/test_task_scheduler_queue.py`
- Reference: `docs/superpowers/specs/2026-04-06-orphan-schedule-cleanup-design.md`

- [ ] **Step 1: Write the failing test expectation**

Change the missing-agent scheduler test so it expects `TaskScheduleUpdate(is_active=False, last_run_at=current_time)` and no retry backoff fields.

- [ ] **Step 2: Run the targeted scheduler test file and observe failure**

Run:

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_task_scheduler_queue.py -v
```

Expected: the missing-agent test fails because current code still increments `retry_count` and pushes `next_run_at` forward.

- [ ] **Step 3: Implement the minimal scheduler fix**

In `src/scheduler/task_scheduler.py`, replace the current missing-agent retry branch with a `TaskScheduleDAO.update()` call that sets:

```python
TaskScheduleUpdate(
    id=schedule.id,
    is_active=False,
    last_run_at=current_time,
)
```

- [ ] **Step 4: Re-run the targeted scheduler test file**

Run:

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_task_scheduler_queue.py -v
```

Expected: all tests in that file pass.

### Task 2: Remove the known orphan template tasks

**Files:**
- Runtime cleanup only: database rows in `tasks`

- [ ] **Step 1: Delete the known orphan template task IDs**

Run a one-off cleanup using `TaskDAO.delete()` for these template task IDs:

```text
446b953b-314e-4cae-a46c-a4a1b88d05b1
017655c5-6e0e-4902-a868-988db91b3c33
d90b388b-8ef8-4bfa-b902-4aa5df0f11cb
79346895-5113-485b-ab0e-38d5e3a8dff5
6db6037a-67ee-4c6f-a177-54c071bcdad6
```

- [ ] **Step 2: Verify the orphan tasks are gone**

Run a read-only query for those IDs and confirm each returns `None`.

- [ ] **Step 3: Verify no due orphan schedules remain**

Run a read-only due-schedules query and confirm the count stays `0` after cleanup.

## Self-Review

- **Spec coverage:** The plan covers both approved actions: deleting the existing orphan tasks and changing scheduler behavior so invalid schedules stop retrying.
- **Placeholder scan:** No `TODO` or undefined follow-up steps remain.
- **Type consistency:** The plan consistently uses `TaskScheduleUpdate`, `is_active=False`, `last_run_at`, and `TaskDAO.delete()`.
