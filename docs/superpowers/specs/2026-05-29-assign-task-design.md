# assign_task Root Task Design

## Goal

Implement `assign_task` as the Butler-facing tool for creating a trackable root task. The tool creates the root task record and a fixed initial workflow skeleton, then returns a generated task id that the user can use later to enquire about progress.

`assign_task` does not execute the task, run sub-agents, ask follow-up questions, or update progress. Those responsibilities belong to later dispatcher, brainstorm, planning, review, enquire, and update tools.

## User Flow

1. The Butler decides a user request is complex enough to track.
2. The Butler asks the user whether to create a plan task.
3. After user approval, the Butler calls `assign_task` with `task_name` and `goal`.
4. `assign_task` creates one root task and three initial steps: Brainstorm, Planning, and Review.
5. `assign_task` returns `task_id`, task status, and the generated initial step ids.
6. The Butler reports the task id to the user.
7. Later tools use `task_id` or approximate `task_name` to retrieve and advance the task.

## Tool Contract

Tool name: `assign_task`

Input exposed to the LLM:

- `task_name`: short human-readable task name.
- `goal`: clear description of the intended outcome.

Runtime values from LangGraph config:

- `user_db_id`: current user database id.
- `agent_db_id` or resolvable current agent id: Butler or responsible root agent.
- `session_db_id`: current user-to-agent session id, nullable if unavailable.

Successful output:

```json
{
  "accepted": true,
  "task_id": "task_xxxxxxxx",
  "task_name": "...",
  "status": "brainstorm_pending",
  "steps": [
    {
      "step_id": "step_xxxxxxxx",
      "title": "Brainstorm",
      "status": "pending"
    },
    {
      "step_id": "step_yyyyyyyy",
      "title": "Planning",
      "status": "blocked"
    },
    {
      "step_id": "step_zzzzzzzz",
      "title": "Review",
      "status": "blocked"
    }
  ]
}
```

Validation failures return a structured rejection with `accepted: false` and an i18n-backed error string.

## Database Schema

### `assigned_task`

Root metadata for a user-approved tracked task.

```text
id                     integer primary key
task_id                string unique not null
user_id                FK user_acc.id not null
responsible_agent_id   FK agent.id not null
session_id             FK session.id nullable
task_name              string not null
goal                   text not null
status                 string not null default brainstorm_pending
approved_plan_html     text nullable
create_dt              timestamp with timezone not null default now()
update_dt              timestamp with timezone not null default now()
```

Field meaning:

- `responsible_agent_id`: central root task owner, usually the Butler/JARVIS agent.
- `session_id`: main user-to-Butler session where the root task was created.
- `approved_plan_html`: the final user-approved HTML plan from the Brainstorm phase.

### `assigned_task_step`

Step-level execution and agent-to-agent context.

```text
id                  integer primary key
step_id             string unique not null
task_id             FK assigned_task.id not null
parent_step_id      FK assigned_task_step.id nullable
step_type           string not null
title               string not null
goal                text not null
status              string not null
seq_no              integer not null
assign_agent_id     FK agent.id not null
session_id          FK session.id nullable
output_html         text nullable
output_json         text nullable
create_dt           timestamp with timezone not null default now()
update_dt           timestamp with timezone not null default now()
```

Field meaning:

- `assign_agent_id`: agent assigned to perform this step.
- `session_id`: session used for this step, such as agent-to-agent or user-to-agent execution context.
- `parent_step_id`: parent step for execution sub-steps created by Planning.
- `output_html`: HTML output, mainly the Brainstorm plan document.
- `output_json`: structured output, mainly Planning sub-step definitions or Review report.

## Initial Workflow

`assign_task` creates three initial steps in order.

### Step 1: Brainstorm

- `step_type`: `brainstorm`
- `title`: `Brainstorm`
- `status`: `pending`
- `goal`: collect requirements from the user, ask clarifying questions, get user approval, and produce an HTML plan document.
- `assign_agent_id`: initially the current Butler agent unless a later dispatcher assigns a dedicated brainstorm agent.

### Step 2: Planning

- `step_type`: `planning`
- `title`: `Planning`
- `status`: `blocked`
- `goal`: convert the approved HTML plan into executable sub-steps.
- `assign_agent_id`: initially the current Butler agent unless a later dispatcher assigns a dedicated planner agent.
- Dependency: waits for Brainstorm to complete and for `approved_plan_html` to be available.

### Step 3: Review

- `step_type`: `review`
- `title`: `Review`
- `status`: `blocked`
- `goal`: review Planning output before execution starts.
- `assign_agent_id`: initially the current Butler agent unless a later dispatcher assigns a dedicated reviewer agent.
- Dependency: waits for Planning to complete.

Review checks include missing requirements, contradictions, scope creep, unclear acceptance criteria, invalid dependencies, and execution steps that are too vague to verify.

## Status Model

Root task statuses:

- `brainstorm_pending`
- `brainstorm_in_progress`
- `awaiting_plan_approval`
- `planning_pending`
- `review_pending`
- `ready_for_execution`
- `in_progress`
- `completed`
- `cancelled`
- `failed`

Step statuses:

- `pending`
- `blocked`
- `in_progress`
- `awaiting_user`
- `approved`
- `completed`
- `failed`
- `cancelled`

The first implementation only needs to create root status `brainstorm_pending` and step statuses `pending` / `blocked`. Later tools can advance the rest of the workflow.

## Agent-To-Agent Boundary

`assign_task` records agent ownership but does not start agent-to-agent conversations. Starting or resuming step sessions should be handled by a dispatcher or step runner so task creation remains fast, retry-safe, and easy to reason about.

When a runner starts a step, it should create or reuse a session and write the resulting `session_id` to `assigned_task_step.session_id`.

## Review Capability

The fixed Review step is the workflow gate after Planning. A future reusable review tool can also let the Butler validate incoming data at any time. The Review step and the reusable review tool should share the same review criteria, but this design only requires creating the Review step.

## Implementation Notes

- Add SQLAlchemy entities `AssignedTask` and `AssignedTaskStep`.
- Add DTOs and DAOs for creating and reading assigned tasks and steps.
- Add an Alembic migration after `20260528_0009`.
- Route all tool descriptions, field descriptions, validation errors, and logger messages through `backend.i18n.t`.
- Keep `assign_task` input limited to `task_name` and `goal`.
- Generate external ids with a stable prefix such as `task_` and `step_` plus a short UUID-derived suffix.
- Add `assign_task` to the graph tool list used by the Butler path.

## Tests

Required tests:

- `assign_task` schema exposes only `task_name` and `goal`.
- `assign_task` rejects missing or blank task names and goals.
- `assign_task` creates one `assigned_task` row.
- `assign_task` creates Brainstorm, Planning, and Review rows in order.
- Planning and Review are initially `blocked`.
- Tool output includes the generated `task_id` and all three step ids.
- Entity metadata includes `assigned_task` and `assigned_task_step`.
- DTO read models validate from SQLAlchemy attributes.
- i18n keys are used for tool and logger text.

## Out Of Scope

- Enquire/search tool for task status.
- Updating task or step progress.
- Running Brainstorm, Planning, Review, or execution agents.
- Fuzzy task name matching.
- Audit/event log table.
- Full reusable review tool.
