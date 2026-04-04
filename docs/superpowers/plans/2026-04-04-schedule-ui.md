# Schedule UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder schedule tab with a real dashboard UI that shows read-only method schedules and fully manageable message schedules.

**Architecture:** Add a small schedule API surface in `src/api/app.py` that normalizes existing task records into `method` and `message` schedule payloads. Build a `ScheduleTab` React component that consumes the grouped payload, renders a read-only method section, and provides inline CRUD for message schedules.

**Tech Stack:** Python 3.12, aiohttp, SQLAlchemy DAO layer, React 18, TypeScript, Vitest, pytest

---

## File Structure

- Modify: `src/api/app.py` - add schedule list and message schedule mutation endpoints
- Modify: `frontend/src/api/dashboard.ts` - add schedule API clients
- Modify: `frontend/src/types/dashboard.ts` - add schedule payload types
- Modify: `frontend/src/mock/dashboard.ts` - add schedule mock payload
- Modify: `frontend/src/test/setup.ts` - route schedule API calls to mocks
- Modify: `frontend/src/pages/AgentsPage.tsx` - replace placeholder with `ScheduleTab`
- Create: `frontend/src/components/agents/ScheduleTab.tsx` - schedule UI
- Modify: `frontend/src/styles/global.css` - schedule layout styles
- Modify: `frontend/src/i18n/locales/zh-HK/dashboard.json` - schedule strings
- Modify: `frontend/src/i18n/locales/en/dashboard.json` - schedule strings
- Modify: `tests/unit/test_api_app.py` - schedule API tests
- Modify: `frontend/src/pages/__tests__/AgentsPage.test.tsx` - schedule tab rendering tests

## Tasks

### Task 1: Backend schedule API
- [ ] Write failing pytest cases for schedule listing and message-only mutations
- [ ] Run those tests and confirm they fail for missing routes or behavior
- [ ] Add schedule serialization helpers and new aiohttp handlers
- [ ] Re-run targeted pytest until green

### Task 2: Frontend schedule API and types
- [ ] Write failing frontend assertions for schedule tab content
- [ ] Run targeted Vitest and confirm the new expectations fail
- [ ] Add TypeScript schedule models, API functions, mocks, and test fetch setup
- [ ] Re-run targeted Vitest until green

### Task 3: Schedule tab UI
- [ ] Implement `ScheduleTab` with method and message sections
- [ ] Wire create/edit/delete/toggle/refresh actions for message schedules
- [ ] Replace the Agents page placeholder with the new component
- [ ] Add minimal CSS and i18n strings for readability on desktop and mobile

### Task 4: Final verification
- [ ] Run backend targeted tests
- [ ] Run frontend targeted tests
- [ ] Review for method/message boundary regressions before completion
