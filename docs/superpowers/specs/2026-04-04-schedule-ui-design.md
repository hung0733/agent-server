# Schedule UI Design

**Date**: 2026-04-04
**Status**: Approved
**Author**: OpenCode

## Overview

Implement the `AgentsPage` schedule tab as a real schedule management UI.

The UI exposes exactly two schedule task types:
- `method`: read-only schedules created and managed by the backend
- `message`: user-manageable schedules with create, update, delete, toggle, and refresh actions

## Confirmed Requirements

- The tasks table is treated as having two schedule-facing task types: `method` and `message`
- `method` schedules are read-only in the dashboard
- `message` schedules are editable in the dashboard
- Only `message` schedules can be enabled or disabled manually
- Only `message` schedules can be refreshed manually
- Only `message` schedules can change `cron` or `interval`
- `message` schedule form fields are:
  - `name`
  - `prompt`
  - `scheduleType`
  - `scheduleExpression`
  - `isActive`

## UI Structure

The existing `AgentsPage` `schedule` tab becomes a `ScheduleTab` component with two sections:

1. `Method Schedules`
2. `Message Schedules`

The page uses the existing dashboard visual language: cards, compact headers, inline forms, and simple action buttons.

## Backend Design

Add dashboard schedule endpoints in `src/api/app.py`.

### Read endpoint

- `GET /api/dashboard/schedules`
- Returns:
  - `methodSchedules`
  - `messageSchedules`

Each item includes:
- `id`
- `taskId`
- `taskType`
- `name`
- `prompt`
- `scheduleType`
- `scheduleExpression`
- `isActive`
- `nextRunAt`
- `lastRunAt`
- `agentId`
- `agentName`

### Message-only write endpoints

- `POST /api/dashboard/schedules/message`
- `PATCH /api/dashboard/schedules/message/{schedule_id}`
- `DELETE /api/dashboard/schedules/message/{schedule_id}`
- `POST /api/dashboard/schedules/message/{schedule_id}/refresh`

The backend enforces the write boundary. Any write request against a non-`message` schedule returns an error.

## Classification Rules

The schedule API normalizes schedule items into dashboard-facing task types.

- `payload.task_execution_type == "method"` => `method`
- `payload.task_execution_type == "message"` => `message`

This avoids broad schema churn while still presenting only the two supported task types in the UI.

## Form and Interaction Rules

`Message Schedules` use a shared inline create/edit form.

- Create starts with an empty form
- Edit loads the selected schedule into the same form
- Save updates the list in-place
- Delete asks for confirmation first
- Refresh recalculates `next_run_at`
- Failed requests preserve form input and show the backend error

## Validation Rules

- `name` is required
- `prompt` is required
- `scheduleType` must be `cron` or `interval`
- `scheduleExpression` is validated server-side using existing schedule validation

## Testing

### Backend

- list schedules split into `methodSchedules` and `messageSchedules`
- method schedules reject write actions
- message schedules support create, update, delete, and refresh
- invalid `scheduleType` and invalid expressions return errors

### Frontend

- schedule tab renders both sections
- method section shows no write actions
- message section supports create and edit form rendering
- message section shows toggle, refresh, edit, and delete actions

## Out of Scope

- Editing method schedules
- Additional schedule task types
- New scheduler semantics beyond `cron` and `interval`
