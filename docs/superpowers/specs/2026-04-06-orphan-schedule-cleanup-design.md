# Orphan Schedule Cleanup Design

## Problem

The scheduler was repeatedly picking up invalid `scheduled_method` schedules whose template tasks had neither `agent_id` nor payload `agent_instance_id`. Those schedules could never execute successfully, but the current scheduler behavior kept retrying them with backoff, producing noisy logs and stale rows.

## Chosen Approach

Use the smallest corrective change in two parts:

1. Remove the already-identified orphan template tasks that no longer have schedules.
2. Change scheduler handling for missing agent references from retry to deactivation.

## Why This Approach

- It stops the current operational noise immediately.
- It preserves the normal execution path for valid schedules.
- It treats missing agent linkage as invalid data, not a transient runtime failure.

## Behavior Changes

- If a scheduled template lacks both `task.agent_id` and payload `agent_instance_id`, `_execute_schedule()` will mark the schedule inactive instead of scheduling another retry.
- Existing orphan template tasks can be safely deleted once their schedules are gone.

## Testing

- Update the scheduler unit test for missing agent references to assert deactivation instead of retry backoff.
- Run the targeted scheduler unit test file.
- Re-query due schedules after cleanup to confirm the orphan rows are gone.
