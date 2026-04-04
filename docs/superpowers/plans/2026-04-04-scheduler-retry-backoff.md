# Scheduler Retry Backoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backoff retry handling for failed schedules and infinite retry for failed `agent_to_agent` queue tasks.

**Architecture:** Keep retry state for recurring schedules on `task_schedules`, and keep retry state for queue executions on existing `tasks` and `task_queue` rows. Centralize delay calculation in the scheduler so both paths use the same backoff ladder while queue polling respects delayed `scheduled_at` timestamps.

**Tech Stack:** Python 3.12, aiohttp, SQLAlchemy DTO/DAO layer, Alembic, pytest

---

## File Structure

- Modify: `src/scheduler/task_scheduler.py` - add shared retry delay helper, delayed queue polling, schedule retry state updates, and infinite `agent_to_agent` retry behavior
- Modify: `src/db/entity/task_schedule_entity.py` - persist schedule retry count
- Modify: `src/db/dto/task_schedule_dto.py` - expose schedule retry count in DTOs
- Create: `alembic/versions/4d5e6f7a8b9c_add_retry_count_to_task_schedules.py` - schema migration for schedule retry count
- Modify: `tests/unit/test_task_scheduler_queue.py` - regression tests for schedule and queue retry behavior

## Tasks

### Task 1: Write failing scheduler retry tests
- [ ] Add unit tests covering schedule failure backoff, future queue entry deferral, and failed `agent_to_agent` queue requeue
- [ ] Run the targeted unit tests and confirm the new assertions fail for the expected reasons

### Task 2: Implement scheduler retry logic
- [ ] Add a shared backoff helper for retry counts `1, 2, 3, 4, >=5`
- [ ] Update queue polling to skip pending entries whose `scheduled_at` is still in the future
- [ ] Update schedule execution failure handling to increment/reset `task_schedules.retry_count`
- [ ] Update queue execution failure handling so `agent_to_agent` tasks reschedule indefinitely with backoff

### Task 3: Persist schedule retry state
- [ ] Add `retry_count` to the task schedule entity and DTOs
- [ ] Add an Alembic migration that creates the column with default `0` and a non-negative check constraint

### Task 4: Verify targeted tests
- [ ] Run `tests/unit/test_task_scheduler_queue.py -v`
- [ ] Review the final diff to confirm only the intended retry semantics changed
