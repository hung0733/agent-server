# Message Queue Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make message queue concurrency configurable from env with default 4, while ensuring the same `agent_id` only runs one task at a time.

**Architecture:** Keep global worker concurrency in `MessageQueue`, and add per-agent locking inside queue task handling. Read `MESSAGE_QUEUE_MAX_CONCURRENCY` in `main.py` after `.env` is loaded.

**Tech Stack:** Python, asyncio, pytest.

---

### Task 1: Env-Driven Global Concurrency

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] Write tests for default `4` and env override.
- [ ] Run targeted tests and confirm they fail because main still passes `2`.
- [ ] Add `get_message_queue_max_concurrency()` and use it when constructing `MessageQueue`.
- [ ] Run targeted tests and confirm they pass.

### Task 2: Per-Agent Serialization

**Files:**
- Modify: `backend/queues/message_queue.py`
- Modify: `tests/test_message_queue.py`

- [ ] Write a test proving two tasks with the same `agent_id` do not enter handler concurrently.
- [ ] Write a test proving different `agent_id` values can still run concurrently.
- [ ] Update invalid concurrency tests to allow values above `2`.
- [ ] Run targeted tests and confirm they fail before implementation.
- [ ] Add per-agent `asyncio.Lock` handling in `MessageQueue`.
- [ ] Run targeted tests and confirm they pass.

### Task 3: Verification

**Files:**
- Test: `tests/test_message_queue.py`
- Test: `tests/test_main.py`

- [ ] Run `pytest tests/test_message_queue.py tests/test_main.py -q`.
- [ ] Inspect `git diff` to confirm only intended files changed.
