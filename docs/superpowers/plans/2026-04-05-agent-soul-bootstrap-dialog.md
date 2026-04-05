# Agent SOUL Bootstrap Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-step Add Agent flow where the second dialog talks to an LLM through a backend proxy and saves the generated SOUL back into the agent memory block.

**Architecture:** Keep agent creation and SOUL bootstrapping separate. The backend exposes one prompt-building/proxy endpoint for bootstrap chat and one save path through the existing agent update API. The frontend opens a second dialog after agent creation, stores the transcript locally, and closes itself after the SOUL is saved.

**Tech Stack:** aiohttp, existing DAO layer, React, Vitest, Testing Library

---

### Task 1: Backend bootstrap proxy

**Files:**
- Modify: `src/api/new_agent_bootstrap.py`
- Modify: `src/api/app.py`
- Test: `tests/unit/test_api_app.py`

- [ ] Add a failing API test for bootstrap proxy mode handling and save response shape.
- [ ] Implement backend prompt composition for `bootstrap`, `synthesis`, and `build` modes.
- [ ] Implement backend LLM proxy call using the agent's endpoint group.
- [ ] Implement save behavior that writes the generated SOUL via existing memory block update logic.
- [ ] Re-run focused backend verification.

### Task 2: Frontend bootstrap dialog flow

**Files:**
- Modify: `frontend/src/components/agents/AgentTab.tsx`
- Create: `frontend/src/components/agents/SoulBootstrapDialog.tsx`
- Modify: `frontend/src/api/dashboard.ts`
- Modify: `frontend/src/types/dashboard.ts`
- Test: `frontend/src/components/agents/__tests__/AgentTab.test.tsx`
- Test: `frontend/src/api/__tests__/agents.test.ts`

- [ ] Add failing frontend tests for the two-step add flow.
- [ ] Add dashboard API client helpers for bootstrap chat.
- [ ] Implement the SOUL bootstrap dialog and transcript handling.
- [ ] Update `AgentTab` to open the second dialog after successful create and persist the returned SOUL into local state.
- [ ] Re-run focused frontend verification.

### Task 3: Final verification

**Files:**
- Modify: `tests/unit/test_api_app.py`
- Modify: `frontend/src/components/agents/__tests__/AgentTab.test.tsx`

- [ ] Run compile-level verification on modified Python files.
- [ ] Run the targeted unit tests that do not require forbidden DB backup bypasses.
- [ ] Report any remaining environment blockers explicitly.
