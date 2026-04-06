# Tool Call Persistence Design

## Problem

The repository already has a `tool_calls` table plus entity, DTO, DAO, migration, and database tests, but the runtime tool execution path does not write any rows into that table. As a result, actual tool invocations are not persisted.

## Chosen Approach

Persist tool execution inside `src/tools/tools.py`, where DB-registered tools are wrapped into runtime executors.

1. Pass `tool_id`, `tool_version_id`, and `task_id` into the executor wrapper.
2. Create a `tool_calls` row with `status="running"` immediately before the real tool function runs.
3. Update that row to `completed` or `failed` after execution, including `duration_ms` and normalized output or error text.

## Why This Approach

- It records only real executions, not model-proposed tool calls.
- It keeps the change at the execution source of truth for DB-registered tools.
- It already has access to the tool registry metadata needed by `tool_calls`.

## Behavior Changes

- Tools loaded through `get_tools()` now persist a `tool_calls` row when `task_id` is available in the graph runtime config metadata.
- Successful executions store `input`, `output`, `status="completed"`, and `duration_ms`.
- Failed executions store `input`, `status="failed"`, `error_message`, and `duration_ms`, then re-raise the original tool error.
- If `task_id` is missing, tool execution continues normally and no `tool_calls` row is written.
- Persistence failures are logged but do not block the real tool execution path.

## Testing

- Add focused unit tests around the tool executor wrapper in `tests/unit/test_tools_tool_call_persistence.py`.
- Verify success persistence, failure persistence, and the no-`task_id` skip path.
- Run the targeted unit test file.
